"""Volumes worked out by hand from the dimensions, independent of the builders.

A rounded rectangle moved inward by `i` keeps concentric corners, so its area is quadratic in
`i`; between two heights where the inset changes linearly the volume is exactly Simpson's rule.
"""

from __future__ import annotations

import math
from itertools import pairwise

CORNER = 4 - math.pi


def area(width: float, depth: float, radius: float, inset: float = 0.0) -> float:
    r = max(radius - inset, 0.0)
    return (width - 2 * inset) * (depth - 2 * inset) - CORNER * r * r


def frustum(width: float, depth: float, radius: float, points: list[tuple[float, float]]) -> float:
    """Volume inside the outline, inset by a piecewise-linear `(inset, z)` profile."""
    total = 0.0
    for (i0, z0), (i1, z1) in pairwise(points):
        h = abs(z1 - z0)
        mid = (i0 + i1) / 2
        total += (
            h
            * (
                area(width, depth, radius, i0)
                + 4 * area(width, depth, radius, mid)
                + area(width, depth, radius, i1)
            )
            / 6
        )
    return total


def fillet_loss(width: float, depth: float, radius: float, fillet: float, angle: float) -> float:
    """Material a fillet of radius `fillet` takes off an edge of `angle` radians running round
    the outline."""
    section = fillet**2 * (1 / math.tan(angle / 2) - (math.pi - angle) / 2)
    perimeter = 2 * (width + depth) - (8 - 2 * math.pi) * radius
    return section * perimeter


def bin_volume(
    units_x: int,
    units_y: int,
    units_z: int,
    lip: str = "default",
    wall: float = 1.2,
    holes: float = 0.0,
    pitch: float = 42.0,
    size: tuple[float, float] | None = None,
) -> float:
    """A bin of the web generator's dimensions, written out from its drawing. A `size` trims it
    from the grid's -X/-Y corner, narrowing the feet it cuts through and dropping any foot
    narrower than its corners."""
    gap, r = 0.62, 3.75
    width, depth = units_x * pitch - gap, units_y * pitch - gap
    if size is not None:
        width, depth = min(size[0] - gap / 2, width), min(size[1] - gap / 2, depth)

    def spans(units: int, extent: float) -> list[float]:
        kept = []
        for index in range(units):
            low = index * pitch
            span = min(low + pitch - gap, extent) - low
            if span < 2 * r:
                break
            kept.append(span)
        return kept

    profile = [(0.0, 4.75), (2.15, 2.6), (2.15, 0.8), (2.95, 0.0)]
    feet = sum(
        frustum(a, b, r, profile) for a in spans(units_x, width) for b in spans(units_y, depth)
    )
    floor = 4.75 + 1.21
    nominal = 7 * units_z
    if lip == "none":
        top = nominal + 4.85
        body = area(width, depth, r) * (top - 4.75)
        cavity = area(width, depth, r, wall) * (top - floor)
        return feet + body - cavity - holes
    apex = nominal + 4.995
    if lip == "default":
        # (inset, depth below the apex); the lip slope comes back out to the wall
        lip_points = [(0.0, 0.0), (2.15, 2.15), (2.15, 3.95), (2.95, 4.75), (2.95, 5.95)]
        back = 5.95 + (2.95 - wall)
    else:
        lip_points = [(0.0, 0.0), (1.95, 1.95), (1.95, 3.75)]
        back = 3.75 + (1.95 - wall)
    inner = [*lip_points, (wall, back), (wall, apex - floor)]
    cavity = frustum(width, depth, r, [(i, apex - d) for i, d in inner])
    body = area(width, depth, r) * (apex - 4.75)
    loss = fillet_loss(width, depth, r, 0.1, math.pi / 4)
    return feet + body - cavity - holes - loss


def baseplate_volume(units_x: int, units_y: int, lift: float = 0.0, holes: float = 0.0) -> float:
    """A baseplate of the web generator's dimensions: pockets meet in sharp corners, and only
    the corners of the plate are rounded, r 4 at the top."""
    pitch, r = 42.0, 4.0
    height = 4.65 + lift
    profile = [(0.0, height), (2.15, height - 2.15), (2.15, height - 3.95), (2.85, lift)]

    def pocket(rounded: int) -> float:
        def at(inset: float) -> float:
            return (pitch - 2 * inset) ** 2 - rounded * (1 - math.pi / 4) * (r - inset) ** 2

        return sum(
            abs(z1 - z0) * (at(i0) + 4 * at((i0 + i1) / 2) + at(i1)) / 6
            for (i0, z0), (i1, z1) in pairwise(profile)
        )

    total = area(units_x * pitch, units_y * pitch, r) * height
    for i in range(units_x):
        for j in range(units_y):
            corners = (
                (i == 0 and j == 0) + (i == units_x - 1 and j == 0)
                + (i == units_x - 1 and j == units_y - 1) + (i == 0 and j == units_y - 1)
            )  # fmt: skip
            total -= pocket(corners)
            if lift:
                # Below the profile the pocket is square; a pad fills each corner from 9 mm out
                # to the wall, its inner corner rounded r 4.5, and covers the pocket's corner
                half = pitch / 2 - 2.85
                pad = (half - 9.0) ** 2 - (1 - math.pi / 4) * 4.5**2
                total -= ((2 * half) ** 2 - 4 * pad) * lift
    return total - holes


def polygon_area(points: list[tuple[float, float]]) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in pairwise([*points, points[0]]))) / 2
