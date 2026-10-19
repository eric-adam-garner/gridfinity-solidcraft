"""Cross-sections of bin walls: where the lip and the outer wall leave the inside of a bin."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from gridfinity.standard import Profile

EPSILON = 1e-9


def inset_at(profile: Profile, depth: float) -> float:
    """The profile's inset at `depth`, zero past its last point."""
    if depth < profile[0][1] - EPSILON or depth > profile[-1][1] + EPSILON:
        return 0.0
    for (i0, d0), (i1, d1) in pairwise(profile):
        if d0 - EPSILON <= depth <= d1 + EPSILON:
            if d1 - d0 < EPSILON:
                return max(i0, i1)
            return i0 + (i1 - i0) * (depth - d0) / (d1 - d0)
    return profile[-1][0]


def inner_surface(
    lip: Profile, wall: float, wall_from: float, until: float
) -> list[tuple[float, float]]:
    """The inner face of a lip of section `lip` over a wall `wall` thick whose top lies
    `wall_from` below the lip's apex, from the apex down to `until`, as `(inset, depth)` points.

    The material at each depth reaches as far in as the lip or the wall does, whichever is
    further; where the wall's top stands proud of the lip the face steps in flat.
    """

    def value(depth: float, below_wall_top: bool) -> float:
        lip_inset = inset_at(lip, depth)
        return max(lip_inset, wall) if below_wall_top else lip_inset

    depths = {0.0, until}
    depths.update(d for _, d in lip if 0 < d < until)
    if 0 <= wall_from <= until:
        depths.add(wall_from)
    for (i0, d0), (i1, d1) in pairwise(lip):
        if abs(i1 - i0) > EPSILON and (i0 - wall) * (i1 - wall) < 0:
            crossing = d0 + (wall - i0) * (d1 - d0) / (i1 - i0)
            if wall_from <= crossing <= until:
                depths.add(crossing)

    points: list[tuple[float, float]] = [(0.0, 0.0)]
    for depth in sorted(depths):
        left = value(depth, depth > wall_from + EPSILON)
        right = value(depth, depth >= wall_from - EPSILON)
        for inset in (left, right):
            if abs(inset - points[-1][0]) > EPSILON or abs(depth - points[-1][1]) > EPSILON:
                points.append((inset, depth))
    return simplify(points)


def simplify(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """`points` without repeats and without points in the middle of a straight run."""
    out: list[tuple[float, float]] = []
    for point in points:
        if out and abs(point[0] - out[-1][0]) < EPSILON and abs(point[1] - out[-1][1]) < EPSILON:
            continue
        while len(out) >= 2 and _collinear(out[-2], out[-1], point):
            out.pop()
        out.append(point)
    return out


def _collinear(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return abs(cross) < 1e-9
