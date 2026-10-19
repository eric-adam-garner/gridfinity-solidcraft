"""Solids built as closed shells of surfaces stitched together.

Every face is a planar patch, a straight extrusion or a ruled loft between two loops, so no
boolean runs while the shell is built. Neighbouring faces must share their edges exactly: where
one face's edge is broken into pieces, the face next to it has to be broken at the same points.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from solidcraft_script.loops import Circle, Point2, RoundedRect, Segment
from solidcraft_script.script import Plane, Script

type Shape = RoundedRect | Circle | Sequence[Segment]
type ProfilePoint = tuple[float, float]


@dataclass(frozen=True)
class Section:
    """A sketch of planar loops at one height."""

    sketch: str
    z: float


class ShellBuilder:
    """Collects surface bodies that close into one solid and stitches them."""

    def __init__(self, script: Script, body: str, label: str | None = None) -> None:
        self.script = script
        self.body = body
        self.label = label or body
        self.surfaces: list[str] = []
        self.features: list[str] = []

    def _name(self, kind: str) -> str:
        return self.script.unique(f"{self.label}{kind}")

    def _surface(self, command: str, kind: str, **params: object) -> None:
        name = self._name(kind)
        body = self.script.unique(f"{self.label}_{kind}")
        self.script.add(command, name=name, body_name=body, **params)
        self.features.append(name)
        self.surfaces.append(body)

    def section(self, z: float, shapes: Sequence[Shape], kind: str = "Loop") -> Section:
        name = self._name(kind)
        with self.script.sketch(name, Plane.horizontal(z)) as sketch:
            for shape in shapes:
                sketch.shape(shape)
        self.features.append(name)
        return Section(name, z)

    def patch(self, section: Section, points: Sequence[Point2], kind: str = "Cap") -> None:
        """One planar face per region of `section` picked by a point inside it."""
        for point in points:
            self._surface(
                "surface.patch",
                kind,
                sketch=section.sketch,
                profiles=[{"point": list(point)}],
            )

    def extrude(
        self,
        section: Section,
        height: float,
        point: Point2 | None = None,
        kind: str = "Band",
    ) -> None:
        """The side walls of a region of `section` (all of it without `point`), `height` up."""
        params: dict[str, object] = {"sketch": section.sketch, "distance": height}
        if point is not None:
            params["profiles"] = [{"point": list(point)}]
        self._surface("surface.extrude", kind, **params)

    def extrude_curves(
        self, section: Section, curves: Sequence[str], height: float, kind: str = "Band"
    ) -> None:
        self._surface(
            "surface.extrude",
            kind,
            sketch=section.sketch,
            curves=list(curves),
            distance=height,
        )

    def loft(
        self,
        lower: Section,
        upper: Section,
        point: Point2,
        upper_point: Point2 | None = None,
    ) -> None:
        """A ruled face between the loops picked by a point in two sections."""
        sections = [
            {"sketch": lower.sketch, "profiles": [{"point": list(point)}]},
            {
                "sketch": upper.sketch,
                "profiles": [{"point": list(upper_point or point)}],
            },
        ]
        self._surface("surface.loft", "Ruled", sections=sections)

    def plane_patch(self, plane: Plane, points: Sequence[Point2], kind: str = "Side") -> None:
        """A planar polygon face drawn on any sketch plane."""
        name = self._name(f"{kind}Sketch")
        with self.script.sketch(name, plane) as sketch:
            sketch.polyline(points, closed=True)
        self.features.append(name)
        self._surface("surface.patch", kind, sketch=name)

    def stitch(self) -> str:
        """Sew every surface into one body named `body`; fold the build into a timeline folder."""
        name = self._name("Stitch")
        self.script.add("surface.stitch", bodies=self.surfaces, name=name)
        self.features.append(name)
        self.script.add("body.rename", body=self.surfaces[0], name=self.body)
        self.script.group(self.label, self.features)
        return self.body


def sweep_profile(
    shell: ShellBuilder,
    outlines: Sequence[RoundedRect],
    profile: Sequence[ProfilePoint],
    kind: str = "Band",
    breaks: Sequence[float] = (),
) -> dict[int, Section]:
    """The faces of an open polyline of `(inset, z)` points swept around each of `outlines`.

    Insets are measured inward from an outline and keep its corners concentric. A step with no
    height becomes a flat ring, one with no change of inset a straight wall, any other a ruled
    loft. All outlines share one sketch per profile point; the sketch of each point is returned
    by its index. Every loop's straight sides break at `breaks`, offsets from its outline's
    centre along the side, so that faces meeting a loop in pieces can share its edges.
    """

    def loop(outline: RoundedRect, inset: float) -> Shape:
        rect = outline.inset(inset)
        return rect.segments(side_points(rect, breaks)) if breaks else rect

    sections: dict[int, Section] = {}

    def at(index: int) -> Section:
        if index not in sections:
            inset, z = profile[index]
            sections[index] = shell.section(z, [loop(o, inset) for o in outlines])
        return sections[index]

    for index in range(len(profile) - 1):
        (inset0, z0), (inset1, z1) = profile[index], profile[index + 1]
        if abs(z1 - z0) < 1e-9:
            if abs(inset1 - inset0) < 1e-9:
                continue
            loops = [loop(o, i) for o in outlines for i in (inset0, inset1)]
            ring = shell.section(z0, loops, kind="Ring")
            shell.patch(ring, [_between(o, inset0, inset1) for o in outlines], kind="Flat")
        elif abs(inset1 - inset0) < 1e-9:
            low = index if z0 < z1 else index + 1
            # One extrusion takes every loop of the sketch
            shell.extrude(at(low), abs(z1 - z0), kind=kind)
        else:
            low, high = (index, index + 1) if z0 < z1 else (index + 1, index)
            for outline in outlines:
                shell.loft(at(low), at(high), outline.center)
    return sections


def _between(outline: RoundedRect, inset0: float, inset1: float) -> Point2:
    """A point between two insets of `outline`, halfway along its bottom side."""
    return (outline.center[0], outline.bounds[1] + (inset0 + inset1) / 2)


def split_wall(
    shell: ShellBuilder,
    outline: RoundedRect,
    z0: float,
    z1: float,
    bottom_splits: Sequence[Point2] = (),
    top_splits: Sequence[Point2] = (),
) -> None:
    """The vertical wall around `outline` from `z0` to `z1`.

    Its bottom and top edges are broken at the given points on the straight sides, so that faces
    meeting the wall in several pieces share its edges. With no breaks it is one extrusion.
    """
    if not bottom_splits and not top_splits:
        shell.extrude(shell.section(z0, [outline]), z1 - z0, outline.center, kind="Wall")
        return
    x0, y0, x1, y1 = outline.bounds
    r = outline.radius
    along_x, along_y = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    up = (0.0, 0.0, 1.0)
    # Each side: its sketch plane (sketch x along the side, sketch y up), the world axis it runs
    # along, the world axis across it and where it sits on that axis
    sides = (
        (Plane((0.0, y0, 0.0), along_x, up), 0, 1, y0),
        (Plane((x1, 0.0, 0.0), along_y, up), 1, 0, x1),
        (Plane((0.0, y1, 0.0), along_x, up), 0, 1, y1),
        (Plane((x0, 0.0, 0.0), along_y, up), 1, 0, x0),
    )
    for plane, along, across, at in sides:
        start, end = (x0 + r, x1 - r) if along == 0 else (y0 + r, y1 - r)
        lower = _breaks(start, end, [p[along] for p in bottom_splits if abs(p[across] - at) < 1e-6])
        upper = _breaks(start, end, [p[along] for p in top_splits if abs(p[across] - at) < 1e-6])
        points = [(s, z0) for s in lower] + [(s, z1) for s in reversed(upper)]
        shell.plane_patch(plane, points, kind="Side")
    if r > 0:
        arcs = shell.section(z0, [outline.corner_arcs()], kind="Corners")
        for index in range(4):
            shell.extrude_curves(arcs, [f"a{index + 1}"], z1 - z0, kind="Corner")


def _breaks(start: float, end: float, cuts: Sequence[float]) -> list[float]:
    inside = sorted({round(c, 9) for c in cuts if start + 1e-6 < c < end - 1e-6})
    return [start, *inside, end]


def stepped_holes(
    shell: ShellBuilder,
    z: float,
    steps: Sequence[tuple[float, float]],
    centers: Sequence[Point2],
    up: bool = True,
    through: bool = False,
) -> None:
    """The inside faces of round holes that open on a face at height `z` and run up (or down)
    into the solid in steps of `(radius, depth from the opening)`.

    The face they open on must carry circles of the first radius as islands. A hole that goes
    `through` ends on a face that carries circles of the last radius instead of a flat end.
    """
    sign = 1.0 if up else -1.0
    previous = 0.0
    for index, (radius, depth) in enumerate(steps):
        start = z + sign * (previous if up else depth)
        band = shell.section(start, [Circle(c, radius) for c in centers], kind="HoleLoop")
        shell.extrude(band, depth - previous, kind="HoleWall")
        if index + 1 < len(steps):
            following = steps[index + 1][0]
            rings = [Circle(c, r) for c in centers for r in (radius, following)]
            ring = shell.section(z + sign * depth, rings, kind="HoleStepLoop")
            middle = (radius + following) / 2
            shell.patch(ring, [(c[0] + middle, c[1]) for c in centers], kind="HoleStep")
        previous = depth
    if not through:
        ends = [Circle(c, steps[-1][0]) for c in centers]
        end = shell.section(z + sign * previous, ends, kind="HoleEndLoop")
        shell.patch(end, list(centers), kind="HoleEnd")


def side_points(rect: RoundedRect, offsets: Sequence[float]) -> list[Point2]:
    """Points on each straight side of `rect` at the given offsets from its centre."""
    x0, y0, x1, y1 = rect.bounds
    cx, cy = rect.center
    points: list[Point2] = []
    for offset in offsets:
        points += [(cx + offset, y0), (cx + offset, y1), (x0, cy + offset), (x1, cy + offset)]
    return points
