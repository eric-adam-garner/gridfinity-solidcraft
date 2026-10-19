"""The feet under a bin: one per grid cell, with magnet and screw holes in their soles."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from gridfinity.config import ConfigError, Grid, Holes, HoleStyle
from gridfinity.standard import Standard
from solidcraft_script.loops import Circle, Line, Point2, RoundedRect
from solidcraft_script.shells import ShellBuilder, stepped_holes, sweep_profile


@dataclass(frozen=True)
class HoleGroup:
    """Holes that share one stack of `(radius, depth)` steps."""

    steps: tuple[tuple[float, float], ...]
    centers: tuple[Point2, ...]


def cell_tops(grid: Grid, std: Standard) -> list[RoundedRect]:
    size = grid.unit_size - std.clearance
    return [RoundedRect(c, size, size, std.corner_radius) for c in grid.cells()]


def outline(grid: Grid, std: Standard) -> RoundedRect:
    return RoundedRect(
        (0.0, 0.0),
        grid.width - std.clearance,
        grid.depth - std.clearance,
        std.corner_radius,
    )


def add_feet(shell: ShellBuilder, grid: Grid, std: Standard, holes: Holes) -> list[Point2]:
    """Feet under every cell, the underside between them and the holes in their soles.

    Returns the points where the bin's outer wall must break its bottom edge to meet them.
    """
    tops = cell_tops(grid, std)
    height = std.foot_height
    profile = [(inset, height - depth) for inset, depth in std.foot]
    sections = sweep_profile(shell, tops, profile, kind="Foot")
    groups = hole_groups(grid, std, holes)
    soles = [top.inset(std.foot_inset) for top in tops]
    if groups:
        islands = [Circle(c, g.steps[0][0]) for g in groups for c in g.centers]
        sole = shell.section(0.0, [*soles, *islands], kind="SoleLoop")
    else:
        sole = sections[len(profile) - 1]
    shell.patch(sole, [top.center for top in tops], kind="Sole")
    for group in groups:
        stepped_holes(shell, 0.0, group.steps, group.centers)

    connectors = perimeter_connectors(grid, std)
    if len(tops) > 1:
        under = shell.section(height, [*tops, *([c] for c in connectors)], kind="UndersideLoop")
        shell.patch(under, gap_points(grid), kind="Underside")
    return [p for c in connectors for p in (c.start, c.end)]


def hole_groups(grid: Grid, std: Standard, holes: Holes) -> list[HoleGroup]:
    offset = std.hole_offset(grid.unit_size)
    magnet_r = holes.magnet_diameter / 2
    if holes.any:
        widest = max(magnet_r if holes.magnets != HoleStyle.NONE else 0.0, std.screw_radius)
        reach = (grid.unit_size - std.clearance) / 2 - std.foot_inset
        if offset - widest <= 0 or offset + widest >= reach:
            raise ConfigError(
                f"holes of radius {widest:g} at {offset:g} from the cell centre do not fit a "
                f"{grid.unit_size:g} mm grid unit"
            )
    magnets = set(hole_positions(grid, std, holes.magnets))
    screws = set(hole_positions(grid, std, holes.screws))
    magnet = (magnet_r, holes.magnet_height)
    screw = (std.screw_radius, std.screw_depth)
    stacks: dict[tuple[tuple[float, float], ...], list[Point2]] = {}
    for point in sorted(magnets | screws):
        if point in magnets and point in screws:
            steps = (magnet, screw) if screw[1] > magnet[1] else (magnet,)
        else:
            steps = (magnet,) if point in magnets else (screw,)
        stacks.setdefault(steps, []).append(point)
    return [HoleGroup(steps, tuple(points)) for steps, points in stacks.items()]


def hole_positions(grid: Grid, std: Standard, style: HoleStyle) -> list[Point2]:
    """Hole centres for one style: four per cell, or the one nearest each corner of the part."""
    if style == HoleStyle.NONE:
        return []
    offset = std.hole_offset(grid.unit_size)
    every = [
        (round(cx + sx * offset, 9), round(cy + sy * offset, 9))
        for cx, cy in grid.cells()
        for sx in (-1, 1)
        for sy in (-1, 1)
    ]
    if style == HoleStyle.FULL:
        return every
    corners = [(sx * grid.width, sy * grid.depth) for sx in (-1, 1) for sy in (-1, 1)]
    return sorted({min(every, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2) for x, y in corners})


def perimeter_connectors(grid: Grid, std: Standard) -> list[Line]:
    """Pieces of the outline between neighbouring cells' straight edges, where the underside
    between the feet meets the outer wall."""
    size = grid.unit_size - std.clearance
    straight = size / 2 - std.corner_radius
    edge_x = (grid.width - std.clearance) / 2
    edge_y = (grid.depth - std.clearance) / 2
    cells = grid.cells()
    columns = sorted({x for x, _ in cells})
    rows = sorted({y for _, y in cells})
    lines: list[Line] = []
    for a, b in pairwise(columns):
        for y in (-edge_y, edge_y):
            lines.append(Line((a + straight, y), (b - straight, y)))
    for a, b in pairwise(rows):
        for x in (-edge_x, edge_x):
            lines.append(Line((x, a + straight), (x, b - straight)))
    return lines


def gap_points(grid: Grid) -> list[Point2]:
    """A point in each separate region of the underside between feet."""
    cells = grid.cells()
    columns = sorted({x for x, _ in cells})
    rows = sorted({y for _, y in cells})
    if len(columns) > 1 and len(rows) > 1:
        return [((columns[0] + columns[1]) / 2, rows[0])]
    if len(columns) > 1:
        return [((a + b) / 2, rows[0]) for a, b in pairwise(columns)]
    return [(columns[0], (a + b) / 2) for a, b in pairwise(rows)]
