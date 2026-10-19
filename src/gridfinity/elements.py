"""Walls, ledges and scoops inside a bin, placed on the subdivided grid.

Each element is drawn as a cross-section on a plane across its line and extruded along it. The
elements are joined into one body, trimmed to the middle of the outer wall (which rounds their
ends into the bin's corners) and joined to the bin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gridfinity.config import BoxConfig, Element, ElementKind, LipStyle, Orientation
from solidcraft_script.loops import Arc, Line, Point2, Segment
from solidcraft_script.script import Plane, Script

if TYPE_CHECKING:
    from gridfinity.box import BinShape

# How far elements reach down into the floor, so that they cross it rather than touch it
SINK = 0.5
# Past the outline, so that the trim is what ends an element at the outer wall
OVERHANG = 1.0
# A scoop on the outer wall stands this far clear of the deepest point of the lip
SCOOP_CLEARANCE = 0.05
THIN_LIP_SCOOP_RISE = 1.2
SCOOP_TOP_GAP = 0.2
SCOOP_BASE = 0.2
SHORT_BULGE_REDUCTION = 0.05


@dataclass(frozen=True)
class Placement:
    """Where an element runs: its plane across the line at its start, its length, the line's
    position across the plane and the side it faces (+1 or -1)."""

    plane: Plane
    length: float
    line: float
    facing: int
    on_edge: bool


def add_elements(script: Script, config: BoxConfig, shape: BinShape, body: str) -> None:
    if not config.elements:
        return
    names = []
    for index, element in enumerate(config.elements, 1):
        name = f"{element.kind.value.capitalize()}{index}"
        place = placement(config, element)
        with script.sketch(f"{name}Section", place.plane) as sketch:
            sketch.segments(section(config, shape, element, place))
        script.add(
            "solid.extrude",
            sketch=f"{name}Section",
            distance=place.length,
            operation="new",
            name=name,
            body_name=name,
        )
        names.append(name)
    first = names[0]
    if len(names) > 1:
        script.add("solid.combine", target=first, tools=names[1:], operation="join")
    trim = shape.outline.inset(shape.wall / 2)
    with script.sketch("ElementTrimSection", Plane.horizontal(shape.floor - SINK - 1)) as sketch:
        sketch.rounded_rectangle(trim)
    script.add(
        "solid.extrude",
        sketch="ElementTrimSection",
        distance=shape.height - shape.floor + SINK + 2,
        operation="new",
        name="ElementTrim",
        body_name="ElementTrim",
    )
    script.add("solid.combine", target="ElementTrim", tools=[first], operation="intersect")
    script.add("solid.combine", target=body, tools=["ElementTrim"], operation="join")


def placement(config: BoxConfig, element: Element) -> Placement:
    std = config.standard
    u = config.grid.unit_size
    step = u / std.subdivisions
    width, depth = config.grid.width, config.grid.depth
    half_gap = std.clearance / 2
    facing = -1 if element.flip else 1
    if element.orientation == Orientation.X:
        start = _extended(-width / 2 + element.x * step, width / 2)
        end = _extended(-width / 2 + (element.x + element.length) * step, width / 2)
        line, on_edge = _line(
            element.y, config.grid.units_y * std.subdivisions, step, depth, half_gap
        )
        plane = Plane((start, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        return Placement(plane, end - start, line, facing, on_edge)
    start = _extended(-depth / 2 + element.y * step, depth / 2)
    end = _extended(-depth / 2 + (element.y + element.length) * step, depth / 2)
    line, on_edge = _line(element.x, config.grid.units_x * std.subdivisions, step, width, half_gap)
    # Sketch x runs along -X so that the plane's normal, and the extrusion, point along +Y
    plane = Plane((0.0, start, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    return Placement(plane, end - start, -line, -facing, on_edge)


def _extended(value: float, half: float) -> float:
    """An element end on the grid's edge, moved past the outline."""
    if value <= -half + 1e-9:
        return -half - OVERHANG
    if value >= half - 1e-9:
        return half + OVERHANG
    return value


def _line(index: int, last: int, step: float, size: float, half_gap: float) -> tuple[float, bool]:
    """A line's position across the grid; lines on the grid's edge sit on the outer face."""
    if index == 0:
        return -(size / 2 - half_gap), True
    if index == last:
        return size / 2 - half_gap, True
    return -size / 2 + index * step, False


def section(
    config: BoxConfig, shape: BinShape, element: Element, place: Placement
) -> list[Segment]:
    """The element's cross-section in its plane: sketch x across the line, sketch y up."""
    std = config.standard
    short = config.units_z < std.short_units
    top = shape.nominal

    def at(across: float, z: float) -> Point2:
        return (place.line + place.facing * across, z)

    if element.kind == ElementKind.WALL:
        half = config.inner_wall / 2
        points = [
            at(-half, shape.floor - SINK),
            at(half, shape.floor - SINK),
            at(half, top),
            at(-half, top),
        ]
        return _polygon(points)
    if element.kind == ElementKind.LEDGE:
        drop = std.ledge_depth_short if short else std.ledge_depth
        return _polygon([at(0.0, top - drop), at(std.ledge_width, top), at(0.0, top)])

    if place.on_edge:
        back = max(inset for inset, _ in shape.inner) - SCOOP_CLEARANCE
        rise = THIN_LIP_SCOOP_RISE if config.lip == LipStyle.THIN else 0.0
    else:
        back = config.inner_wall / 2
        rise = 0.0
    base = std.element_base
    height = std.scoop_height_short if short else std.scoop_height
    bulge = config.scoop_shape - (SHORT_BULGE_REDUCTION if short else 0.0)
    foot = at(back + std.scoop_width, base)
    head = at(back, base + height)
    arc = _bulge_arc(foot, head, bulge, toward=at(back, base))
    return [
        Line(at(0.0, base - SCOOP_BASE), at(back + std.scoop_width, base - SCOOP_BASE)),
        Line(at(back + std.scoop_width, base - SCOOP_BASE), foot),
        arc,
        Line(head, at(back, top + rise - SCOOP_TOP_GAP)),
        Line(at(back, top + rise - SCOOP_TOP_GAP), at(0.0, top + rise - SCOOP_TOP_GAP)),
        Line(at(0.0, top + rise - SCOOP_TOP_GAP), at(0.0, base - SCOOP_BASE)),
    ]


def _polygon(points: list[Point2]) -> list[Segment]:
    return [Line(a, b) for a, b in zip(points, points[1:] + points[:1], strict=True)]


def _bulge_arc(start: Point2, end: Point2, bulge: float, toward: Point2) -> Arc:
    """The arc from `start` to `end` whose middle stands `bulge` half-chords off the chord, on
    the side of `toward`."""
    mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
    chord = math.dist(start, end)
    nx, ny = -(end[1] - start[1]) / chord, (end[0] - start[0]) / chord
    if (toward[0] - mx) * nx + (toward[1] - my) * ny < 0:
        nx, ny = -nx, -ny
    sagitta = bulge * chord / 2
    radius = (chord**2 / 4 + sagitta**2) / (2 * sagitta)
    # The centre lies on the other side of the chord from the arc's middle
    cx, cy = mx - nx * (radius - sagitta), my - ny * (radius - sagitta)
    # The short way round from start to end
    cross = (start[0] - cx) * (end[1] - cy) - (start[1] - cy) * (end[0] - cx)
    return Arc((cx, cy), start, end, clockwise=cross < 0)
