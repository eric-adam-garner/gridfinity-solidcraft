"""The feet under a bin: one per grid cell, with magnet and screw holes in their soles.

A bin trimmed to a size keeps the grid's -X/-Y corner. The column and row its trim cuts through
get narrower feet with the full profile, and lose them where too little is left for one.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from gridfinity.config import ConfigError, Grid, Holes, HoleStyle
from gridfinity.standard import Standard
from solidcraft_script.loops import Circle, Line, Point2, RoundedRect, Segment
from solidcraft_script.shells import ShellBuilder, stepped_holes, sweep_profile

EPSILON = 1e-6


@dataclass(frozen=True)
class HoleGroup:
    """Holes that share one stack of `(radius, depth)` steps."""

    steps: tuple[tuple[float, float], ...]
    centers: tuple[Point2, ...]


@dataclass(frozen=True)
class Footprint:
    """Where a bin stands: its outline, and the span of the feet's tops in each column and row."""

    outline: RoundedRect
    columns: tuple[tuple[float, float], ...]
    rows: tuple[tuple[float, float], ...]
    # Width of a whole foot's top
    cell: float

    @staticmethod
    def of(
        grid: Grid, std: Standard, size_x: float | None = None, size_y: float | None = None
    ) -> Footprint:
        u, gap, r = grid.unit_size, std.clearance, std.corner_radius
        width = grid.width - gap if size_x is None else min(size_x - gap / 2, grid.width - gap)
        depth = grid.depth - gap if size_y is None else min(size_y - gap / 2, grid.depth - gap)
        x0, y0 = -grid.width / 2 + gap / 2, -grid.depth / 2 + gap / 2
        if min(width, depth) < 2 * r - EPSILON:
            raise ConfigError("the bin is trimmed too small to stand on a foot")
        outline = RoundedRect((x0 + width / 2, y0 + depth / 2), width, depth, r)

        def spans(start: float, count: int, end: float) -> tuple[tuple[float, float], ...]:
            kept = []
            for index in range(count):
                low = start + index * u
                high = min(low + u - gap, end)
                # A foot needs room for its corners
                if high - low < 2 * r - EPSILON:
                    break
                kept.append((low, high))
            return tuple(kept)

        columns = spans(x0, grid.units_x, x0 + width)
        rows = spans(y0, grid.units_y, y0 + depth)
        if not columns or not rows:
            raise ConfigError("the bin is trimmed too small to stand on a foot")
        return Footprint(outline, columns, rows, u - gap)

    def cells(self) -> list[RoundedRect]:
        r = self.outline.radius
        return [
            RoundedRect(((a + b) / 2, (c + d) / 2), b - a, d - c, r)
            for c, d in self.rows
            for a, b in self.columns
        ]

    def whole(self, cell: RoundedRect) -> bool:
        return abs(cell.width - self.cell) < EPSILON and abs(cell.height - self.cell) < EPSILON


def add_feet(
    shell: ShellBuilder, footprint: Footprint, grid: Grid, std: Standard, holes: Holes
) -> list[Point2]:
    """Feet under every cell, the underside between them and the holes in their soles.

    Returns the points where the bin's outer wall must break its bottom edge to meet them.
    """
    tops = footprint.cells()
    height = std.foot_height
    profile = [(inset, height - depth) for inset, depth in std.foot]
    sections = sweep_profile(shell, tops, profile, kind="Foot")
    groups = hole_groups(footprint, grid, std, holes)
    soles = [top.inset(std.foot_inset) for top in tops]
    if groups:
        islands = [Circle(c, g.steps[0][0]) for g in groups for c in g.centers]
        sole = shell.section(0.0, [*soles, *islands], kind="SoleLoop")
    else:
        sole = sections[len(profile) - 1]
    shell.patch(sole, [top.center for top in tops], kind="Sole")
    for group in groups:
        stepped_holes(shell, 0.0, group.steps, group.centers)

    connectors = perimeter_connectors(footprint)
    picks = gap_points(footprint)
    if picks:
        under = shell.section(height, [*tops, *([c] for c in connectors)], kind="UndersideLoop")
        shell.patch(under, picks, kind="Underside")
    return [p for c in connectors for p in (c.start, c.end)]


def hole_groups(footprint: Footprint, grid: Grid, std: Standard, holes: Holes) -> list[HoleGroup]:
    offset = std.hole_offset(grid.unit_size)
    magnet_r = holes.magnet_diameter / 2
    if holes.any:
        widest = max(magnet_r if holes.magnets != HoleStyle.NONE else 0.0, std.screw_radius)
        reach = footprint.cell / 2 - std.foot_inset
        if offset - widest <= 0 or offset + widest >= reach:
            raise ConfigError(
                f"holes of radius {widest:g} at {offset:g} from the cell centre do not fit a "
                f"{grid.unit_size:g} mm grid unit"
            )
    magnets = set(hole_positions(footprint, std, holes.magnets, grid.unit_size))
    screws = set(hole_positions(footprint, std, holes.screws, grid.unit_size))
    magnet = (magnet_r, holes.magnet_height - std.hole_lead)
    screw = (std.screw_radius, std.screw_length - std.hole_lead)
    stacks: dict[tuple[tuple[float, float], ...], list[Point2]] = {}
    for point in sorted(magnets | screws):
        if point in magnets and point in screws:
            steps = (magnet, screw) if screw[1] > magnet[1] else (magnet,)
        else:
            steps = (magnet,) if point in magnets else (screw,)
        stacks.setdefault(steps, []).append(point)
    return [HoleGroup(steps, tuple(points)) for steps, points in stacks.items()]


def hole_positions(
    footprint: Footprint, std: Standard, style: HoleStyle, unit_size: float
) -> list[Point2]:
    """Hole centres for one style, in whole feet only: four per foot, or the one nearest each
    corner of the bin."""
    if style == HoleStyle.NONE:
        return []
    offset = std.hole_offset(unit_size)
    every = [
        (round(cell.center[0] + sx * offset, 9), round(cell.center[1] + sy * offset, 9))
        for cell in footprint.cells()
        if footprint.whole(cell)
        for sx in (-1, 1)
        for sy in (-1, 1)
    ]
    if style == HoleStyle.FULL or not every:
        return every
    x0, y0, x1, y1 = footprint.outline.bounds
    corners = [(x, y) for x in (x0, x1) for y in (y0, y1)]
    return sorted({min(every, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2) for x, y in corners})


def perimeter_connectors(footprint: Footprint) -> list[Segment]:
    """The pieces of the outline that no foot's top edge covers, where the underside between
    and beside the feet meets the outer wall."""
    outline = footprint.outline
    x0, y0, x1, y1 = outline.bounds
    r = outline.radius
    columns, rows = footprint.columns, footprint.rows
    reaches_x1 = abs(columns[-1][1] - x1) < EPSILON
    reaches_y1 = abs(rows[-1][1] - y1) < EPSILON
    pieces: list[Segment] = []

    def uncovered(
        start: float, end: float, covered: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        gaps, at = [], start
        for low, high in sorted(covered):
            if low > at + EPSILON:
                gaps.append((at, low))
            at = max(at, high)
        if end > at + EPSILON:
            gaps.append((at, end))
        return gaps

    def along(spans: tuple[tuple[float, float], ...], present: bool) -> list[tuple[float, float]]:
        return [(low + r, high - r) for low, high in spans] if present else []

    for y, present in ((y0, True), (y1, reaches_y1)):
        for a, b in uncovered(x0 + r, x1 - r, along(columns, present)):
            pieces.append(Line((a, y), (b, y)))
    for x, present in ((x0, True), (x1, reaches_x1)):
        for a, b in uncovered(y0 + r, y1 - r, along(rows, present)):
            pieces.append(Line((x, a), (x, b)))
    # A corner with no foot in it is a corner of the outline itself
    arcs = outline.corner_arcs()
    for arc, covered in zip(
        arcs, (True, reaches_x1, reaches_x1 and reaches_y1, reaches_y1), strict=True
    ):
        if not covered:
            pieces.append(arc)
    return pieces


def gap_points(footprint: Footprint) -> list[Point2]:
    """A point in each separate region of the underside between and beside the feet.

    The strips between columns and between rows each span the bin, so they make one region as
    soon as there are both; otherwise each strip is a region of its own.
    """
    _, _, x1, y1 = footprint.outline.bounds
    columns, rows = footprint.columns, footprint.rows
    across = [(b, c) for (_, b), (c, _) in pairwise(columns)]
    if x1 - columns[-1][1] > EPSILON:
        across.append((columns[-1][1], x1))
    up = [(b, c) for (_, b), (c, _) in pairwise(rows)]
    if y1 - rows[-1][1] > EPSILON:
        up.append((rows[-1][1], y1))
    middle_row = sum(rows[0]) / 2
    middle_column = sum(columns[0]) / 2
    points = [((a + b) / 2, middle_row) for a, b in across]
    points += [(middle_column, (a + b) / 2) for a, b in up]
    if across and up:
        return points[:1]
    return points
