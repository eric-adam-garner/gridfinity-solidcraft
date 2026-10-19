"""Planar outlines made of lines and arcs: the closed loops that sketches draw."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

TOLERANCE = 1e-9

type Point2 = tuple[float, float]


@dataclass(frozen=True)
class Line:
    start: Point2
    end: Point2

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)


@dataclass(frozen=True)
class Arc:
    """An arc about `center` from `start` to `end`, counter-clockwise unless `clockwise`.

    The ends are kept exactly as given so that they meet the curves next to them.
    """

    center: Point2
    start: Point2
    end: Point2
    clockwise: bool = False

    @property
    def radius(self) -> float:
        return math.dist(self.center, self.start)

    @property
    def sweep(self) -> float:
        """Signed angle from start to end, positive counter-clockwise."""
        a0 = math.atan2(self.start[1] - self.center[1], self.start[0] - self.center[0])
        a1 = math.atan2(self.end[1] - self.center[1], self.end[0] - self.center[0])
        ccw = (a1 - a0) % (2 * math.pi)
        return ccw - 2 * math.pi if self.clockwise else ccw

    @property
    def midpoint(self) -> Point2:
        a0 = math.atan2(self.start[1] - self.center[1], self.start[0] - self.center[0])
        angle = a0 + self.sweep / 2
        r = self.radius
        return (self.center[0] + r * math.cos(angle), self.center[1] + r * math.sin(angle))


@dataclass(frozen=True)
class Circle:
    center: Point2
    radius: float

    @property
    def area(self) -> float:
        return math.pi * self.radius**2


type Segment = Line | Arc


@dataclass(frozen=True)
class RoundedRect:
    """An axis-aligned rectangle with four equal corner arcs."""

    center: Point2
    width: float
    height: float
    radius: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"rectangle size must be positive: {self.width} x {self.height}")
        if self.radius < 0 or 2 * self.radius > min(self.width, self.height) + TOLERANCE:
            raise ValueError(
                f"corner radius {self.radius} does not fit {self.width} x {self.height}"
            )

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        cx, cy = self.center
        return (
            cx - self.width / 2,
            cy - self.height / 2,
            cx + self.width / 2,
            cy + self.height / 2,
        )

    @property
    def area(self) -> float:
        return self.width * self.height - (4 - math.pi) * self.radius**2

    @property
    def perimeter(self) -> float:
        return 2 * (self.width + self.height) - (8 - 2 * math.pi) * self.radius

    def inset(self, distance: float) -> RoundedRect:
        """The outline moved inward by `distance` (outward when negative), corners concentric."""
        return RoundedRect(
            self.center,
            self.width - 2 * distance,
            self.height - 2 * distance,
            max(self.radius - distance, 0.0),
        )

    def moved(self, dx: float, dy: float) -> RoundedRect:
        return RoundedRect(
            (self.center[0] + dx, self.center[1] + dy),
            self.width,
            self.height,
            self.radius,
        )

    def corner_centers(self) -> tuple[Point2, Point2, Point2, Point2]:
        """Arc centres: bottom-left, bottom-right, top-right, top-left."""
        x0, y0, x1, y1 = self.bounds
        r = self.radius
        return ((x0 + r, y0 + r), (x1 - r, y0 + r), (x1 - r, y1 - r), (x0 + r, y1 - r))

    def corner_arcs(self) -> tuple[Arc, Arc, Arc, Arc]:
        """Counter-clockwise corner arcs: bottom-left, bottom-right, top-right, top-left."""
        x0, y0, x1, y1 = self.bounds
        r = self.radius
        bl, br, tr, tl = self.corner_centers()
        return (
            Arc(bl, (x0, y0 + r), (x0 + r, y0)),
            Arc(br, (x1 - r, y0), (x1, y0 + r)),
            Arc(tr, (x1, y1 - r), (x1 - r, y1)),
            Arc(tl, (x0 + r, y1), (x0, y1 - r)),
        )

    def contains(self, point: Point2) -> bool:
        x, y = point
        x0, y0, x1, y1 = self.bounds
        if not (x0 - TOLERANCE <= x <= x1 + TOLERANCE and y0 - TOLERANCE <= y <= y1 + TOLERANCE):
            return False
        r = self.radius
        cx = min(max(x, x0 + r), x1 - r)
        cy = min(max(y, y0 + r), y1 - r)
        return math.hypot(x - cx, y - cy) <= r + TOLERANCE

    def segments(self, splits: Sequence[Point2] = ()) -> list[Segment]:
        """The boundary counter-clockwise from the bottom-left corner, each straight side broken at
        the `splits` that lie on it."""
        x0, y0, x1, y1 = self.bounds
        r = self.radius
        arcs = self.corner_arcs()
        sides = (
            ((x0 + r, y0), (x1 - r, y0)),
            ((x1, y0 + r), (x1, y1 - r)),
            ((x1 - r, y1), (x0 + r, y1)),
            ((x0, y1 - r), (x0, y0 + r)),
        )
        loop: list[Segment] = []
        for index, (start, end) in enumerate(sides):
            if r > 0:
                loop.append(arcs[index])
            loop.extend(split_line(Line(start, end), splits))
        return loop


def split_line(line: Line, points: Sequence[Point2]) -> list[Line]:
    """`line` broken at the given points that lie strictly inside it."""
    length = line.length
    if length <= TOLERANCE:
        return []
    dx = (line.end[0] - line.start[0]) / length
    dy = (line.end[1] - line.start[1]) / length
    cuts = []
    for point in points:
        px, py = point[0] - line.start[0], point[1] - line.start[1]
        along = px * dx + py * dy
        across = abs(px * dy - py * dx)
        if across <= 1e-6 and 1e-6 < along < length - 1e-6:
            cuts.append(along)
    stops = [0.0, *sorted({round(c, 9) for c in cuts}), length]

    def at(t: float) -> Point2:
        return (line.start[0] + dx * t, line.start[1] + dy * t)

    return [Line(at(a), at(b)) for a, b in pairwise(stops)]


def round_corner(
    before: Point2, corner: Point2, after: Point2, radius: float, segments: int
) -> list[Point2]:
    """Points that replace `corner` of the polyline before-corner-after with `segments` straight
    pieces of an arc of `radius` tangent to both legs, from the tangent point on the first leg
    to the one on the second."""
    ux, uy = _unit(before[0] - corner[0], before[1] - corner[1])
    vx, vy = _unit(after[0] - corner[0], after[1] - corner[1])
    angle = math.acos(max(-1.0, min(1.0, ux * vx + uy * vy)))
    if angle < 1e-9 or abs(angle - math.pi) < 1e-9:
        return [corner]
    reach = radius / math.tan(angle / 2)
    bx, by = _unit(ux + vx, uy + vy)
    distance = radius / math.sin(angle / 2)
    center = (corner[0] + bx * distance, corner[1] + by * distance)
    start = (corner[0] + ux * reach, corner[1] + uy * reach)
    end = (corner[0] + vx * reach, corner[1] + vy * reach)
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    return [
        (
            center[0] + radius * math.cos(a0 + sweep * k / segments),
            center[1] + radius * math.sin(a0 + sweep * k / segments),
        )
        for k in range(segments + 1)
    ]


def _unit(x: float, y: float) -> Point2:
    length = math.hypot(x, y)
    return (x / length, y / length)
