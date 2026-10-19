"""Baseplates: a pocket for each grid cell that a bin's foot drops into, open underneath, with
optional magnet and screw pads in the pocket corners and connector slots on the outer edges."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from gridfinity.config import BaseplateConfig, ConfigError, HoleStyle
from gridfinity.standard import CLIP, Standard, slot_width
from solidcraft_script.loops import Arc, Circle, Line, Point2, RoundedRect, Segment
from solidcraft_script.script import Plane, Script
from solidcraft_script.shells import (
    ShellBuilder,
    side_points,
    split_wall,
    stepped_holes,
    sweep_profile,
)

BODY = "Baseplate"
# A slot's cutter starts this far outside the plate so that it crosses the outer face
SLOT_OVERRUN = 1.0


@dataclass(frozen=True)
class PlateShape:
    outline: RoundedRect
    cells: tuple[RoundedRect, ...]
    height: float
    # Height of the pads under the pockets; zero without magnets or screws
    lift: float

    @staticmethod
    def of(config: BaseplateConfig) -> PlateShape:
        std = config.standard.baseplate
        grid = config.grid
        u = grid.unit_size
        lift = std.lift if config.holes.any else 0.0
        return PlateShape(
            outline=RoundedRect((0.0, 0.0), grid.width, grid.depth, std.corner_radius),
            cells=tuple(RoundedRect(c, u, u, std.corner_radius) for c in grid.cells()),
            height=std.height + lift,
            lift=lift,
        )


def build_baseplate(config: BaseplateConfig, script: Script | None = None) -> Script:
    config.validate()
    script = script or Script()
    std = config.standard
    plate = std.baseplate
    shape = PlateShape.of(config)
    shell = ShellBuilder(script, BODY, label="Plate")

    connectors = _connectors(config, shape)
    breaks = pad_breaks(config) if shape.lift else ()
    # The outer wall's top edge meets the pockets' top edges and the flats between them
    splits = [p for line in connectors for p in (line.start, line.end)]
    splits += [p for cell in shape.cells for p in side_points(cell, breaks)]
    split_wall(shell, shape.outline, 0.0, shape.height, top_splits=splits)
    top = shell.section(shape.height, [*shape.cells, *([c] for c in connectors)], kind="TopLoop")
    islands = _island_points(config)
    if islands:
        shell.patch(top, islands, kind="Top")

    profile = [(inset, shape.height - depth) for inset, depth in plate.pocket]
    sweep_profile(shell, list(shape.cells), profile, kind="Pocket", breaks=breaks)
    floor_inset = plate.pocket[-1][0]
    bottoms: list[RoundedRect | list[Segment]] = [cell.inset(floor_inset) for cell in shape.cells]
    bottom_islands: list[Circle] = []
    if shape.lift:
        bottoms, bottom_islands = _pads(shell, config, shape, std)
    bottom = shell.section(0.0, [shape.outline, *bottoms, *bottom_islands], kind="BottomLoop")
    x0, y0, _, _ = shape.outline.bounds
    shell.patch(bottom, [(x0 + floor_inset / 2, shape.outline.center[1])], kind="Bottom")
    shell.stitch()
    if config.connectable:
        _slots(script, config, shape)
    _trim(script, config, shape)
    script.add("browser.visibility", visible=False, folder="sketches")
    return script


def _connectors(config: BaseplateConfig, shape: PlateShape) -> list[Line]:
    """Pieces of the outline between neighbouring pockets' straight top edges."""
    u = config.grid.unit_size
    straight = u / 2 - shape.outline.radius
    x0, y0, x1, y1 = shape.outline.bounds
    xs = sorted({c.center[0] for c in shape.cells})
    ys = sorted({c.center[1] for c in shape.cells})
    lines = []
    for a, b in pairwise(xs):
        lines += [Line((a + straight, y), (b - straight, y)) for y in (y0, y1)]
    for a, b in pairwise(ys):
        lines += [Line((x, a + straight), (x, b - straight)) for x in (x0, x1)]
    return lines


def _island_points(config: BaseplateConfig) -> list[Point2]:
    """A point in each flat patch of the top, where pocket corners leave a gap at a grid
    corner: inside the plate, or against its edge."""
    grid = config.grid
    u = grid.unit_size
    x0, y0 = -grid.width / 2, -grid.depth / 2
    inward = 0.3
    points = []
    for i in range(grid.units_x + 1):
        for j in range(grid.units_y + 1):
            on_x_edge = i in (0, grid.units_x)
            on_y_edge = j in (0, grid.units_y)
            if on_x_edge and on_y_edge:
                continue
            x, y = x0 + i * u, y0 + j * u
            if on_x_edge:
                x += inward if i == 0 else -inward
            if on_y_edge:
                y += inward if j == 0 else -inward
            points.append((x, y))
    return points


def _pads(
    shell: ShellBuilder, config: BaseplateConfig, shape: PlateShape, std: Standard
) -> tuple[list[list[Segment]], list[Circle]]:
    """Pads in the four corners of each pocket below the lifted profile, with their magnet
    pockets and screw holes. Returns the pocket outlines and the screw holes at the bottom."""
    plate = std.baseplate
    holes = config.holes
    offset = std.hole_offset(config.grid.unit_size)
    magnet_r = holes.magnet_diameter / 2
    screw_r = plate.screw_diameter / 2
    magnets = holes.magnets != HoleStyle.NONE
    screws = holes.screws != HoleStyle.NONE
    corners = [(sx, sy) for sx in (-1, 1) for sy in (-1, 1)]
    centers = [
        (c.center[0] + sx * offset, c.center[1] + sy * offset)
        for c in shape.cells
        for sx, sy in corners
    ]

    inset = plate.pocket[-1][0]
    tops = [cell.inset(inset) for cell in shape.cells]
    breaks = pad_breaks(config)
    pockets = [_cross(top.center, top.width / 2, offset, plate.pad_radius) for top in tops]
    opening = magnet_r if magnets else screw_r
    loops = [top.segments(side_points(top, breaks)) for top in tops]
    pad_tops = shell.section(
        shape.lift, [*loops, *pockets, *(Circle(c, opening) for c in centers)], kind="PadTopLoop"
    )
    # Near each pocket corner: on the pad, clear of its hole
    near = [top.width / 2 - 0.5 for top in tops]
    picks = [
        (t.center[0] + sx * n, t.center[1] + sy * n)
        for t, n in zip(tops, near, strict=True)
        for sx, sy in corners
    ]
    shell.patch(pad_tops, picks, kind="PadTop")
    walls = shell.section(0.0, pockets, kind="PadWallLoop")
    shell.extrude(walls, shape.lift, kind="PadWall")

    if magnets:
        depth = min(holes.magnet_height, shape.lift)
        steps = [(magnet_r, depth)]
        if screws and depth < shape.lift:
            steps.append((screw_r, shape.lift))
    else:
        steps = [(screw_r, shape.lift)]
    through = steps[-1][1] >= shape.lift
    stepped_holes(shell, shape.lift, steps, centers, up=False, through=through)
    islands = [Circle(c, steps[-1][0]) for c in centers] if through else []
    return pockets, islands


def pad_breaks(config: BaseplateConfig) -> tuple[float, ...]:
    """Offsets from a pocket's centre where the pads' inner edges meet the pocket walls."""
    std = config.standard
    inner = std.hole_offset(config.grid.unit_size) - std.baseplate.pad_radius
    if inner <= 0:
        raise ConfigError(
            f"magnet and screw pads do not fit a {config.grid.unit_size:g} mm grid unit"
        )
    return (-inner, inner)


def _cross(center: Point2, half: float, offset: float, radius: float) -> list[Segment]:
    """The outline, counter-clockwise, of a square pocket of half-size `half` with a pad in
    each corner whose inner corner is rounded about a point `offset` from `center` on both
    axes."""
    cx, cy = center
    h, o, i = half, offset, offset - radius

    def p(x: float, y: float) -> Point2:
        return (cx + x, cy + y)

    pads: list[list[Segment]] = []
    for sx, sy in ((1, -1), (1, 1), (-1, 1), (-1, -1)):
        if sx * sy < 0:
            a, b, c, d = p(sx * i, sy * h), p(sx * i, sy * o), p(sx * o, sy * i), p(sx * h, sy * i)
        else:
            a, b, c, d = p(sx * h, sy * i), p(sx * o, sy * i), p(sx * i, sy * o), p(sx * i, sy * h)
        pads.append([Line(a, b), Arc(p(sx * o, sy * o), b, c, clockwise=True), Line(c, d)])
    loop: list[Segment] = []
    for index, pad in enumerate(pads):
        following = pads[(index + 1) % 4]
        loop += [*pad, Line(pad[-1].end, following[0].start)]
    return loop


def _slots(script: Script, config: BaseplateConfig, shape: PlateShape) -> None:
    """A connector slot at the middle of each grid unit along every outer edge."""
    u = config.grid.unit_size
    width = slot_width(u)
    section = [(max(a, 0.0), b) for a, b in CLIP.slot]
    section = [(min(a, CLIP.slot_depth), b + shape.lift) for a, b in section]
    section = [(-SLOT_OVERRUN if a == 0.0 else a, b) for a, b in section]
    x0, y0, x1, y1 = shape.outline.bounds
    xs = sorted({c.center[0] for c in shape.cells})
    ys = sorted({c.center[1] for c in shape.cells})
    up = (0.0, 0.0, 1.0)
    # Each edge: sketch plane across it at a slot's start (sketch x inward), and where slots go
    edges = []
    for x in xs:
        edges.append((Plane((x - width / 2, y0, 0.0), (0.0, 1.0, 0.0), up), (1.0, 0.0, 0.0)))
        edges.append((Plane((x + width / 2, y1, 0.0), (0.0, -1.0, 0.0), up), (-1.0, 0.0, 0.0)))
    for y in ys:
        edges.append((Plane((x0, y + width / 2, 0.0), (1.0, 0.0, 0.0), up), (0.0, -1.0, 0.0)))
        edges.append((Plane((x1, y - width / 2, 0.0), (-1.0, 0.0, 0.0), up), (0.0, 1.0, 0.0)))
    for index, (plane, _) in enumerate(edges, 1):
        name = f"Slot{index}"
        with script.sketch(f"{name}Section", plane) as sketch:
            sketch.polyline(section, closed=True)
        script.add(
            "solid.extrude", sketch=f"{name}Section", distance=width, operation="cut", name=name
        )


def _trim(script: Script, config: BaseplateConfig, shape: PlateShape) -> None:
    """Cut the plate back to the requested size on its +X and +Y sides."""
    x0, y0, x1, y1 = shape.outline.bounds
    margin = 5.0
    for axis, size in ((0, config.size_x), (1, config.size_y)):
        if size is None:
            continue
        limit = (x0 if axis == 0 else y0) + size
        if limit >= (x1 if axis == 0 else y1) - 1e-9:
            continue
        if axis == 0:
            box = {
                "length": x1 - limit + margin,
                "width": y1 - y0 + 2 * margin,
                "height": shape.height + 2 * margin,
            }
            corner = [limit, y0 - margin, -margin]
        else:
            box = {
                "length": x1 - x0 + 2 * margin,
                "width": y1 - limit + margin,
                "height": shape.height + 2 * margin,
            }
            corner = [x0 - margin, limit, -margin]
        script.add(
            "solid.box",
            corner=corner,
            operation="cut",
            name="TrimX" if axis == 0 else "TrimY",
            **box,
        )
