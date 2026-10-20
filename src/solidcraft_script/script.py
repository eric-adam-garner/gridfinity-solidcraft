"""Build SolidCraft command scripts.

A script is the list of `{command, params}` steps that `solidcraft-cli run`, the MCP `batch`
tool and the control protocol's `engine.batch` all accept, so one script can be run headless or
replayed into the open app.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from solidcraft_script.loops import Arc, Circle, Line, Point2, RoundedRect, Segment

DECIMALS = 6
NAMED_PREFIXES = (
    "solid.",
    "surface.",
    "construct.",
    "sheet.",
    "mesh.",
    "sketch.create",
)

type Point3 = tuple[float, float, float]
type Json = dict[str, Any]


class Operation(StrEnum):
    NEW = "new"
    JOIN = "join"
    CUT = "cut"
    INTERSECT = "intersect"


class Direction(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    SYMMETRIC = "symmetric"


@dataclass(frozen=True)
class Plane:
    """A sketch plane: sketch (x, y) lands at `origin + x * x_dir + y * y_dir`."""

    origin: Point3 = (0.0, 0.0, 0.0)
    x_dir: Point3 = (1.0, 0.0, 0.0)
    y_dir: Point3 = (0.0, 1.0, 0.0)

    @staticmethod
    def horizontal(z: float) -> Plane:
        return Plane(origin=(0.0, 0.0, z))

    def is_horizontal(self) -> bool:
        return self.x_dir == (1.0, 0.0, 0.0) and self.y_dir == (0.0, 1.0, 0.0)

    def params(self) -> Json:
        if self.is_horizontal():
            z = self.origin[2]
            # The offset form keeps the plane on XY, so the app shows it as an offset plane
            return {"plane": "XY", "offset": number(z)} if z else {"plane": "XY"}
        return {
            "plane": {
                "origin": [number(v) for v in self.origin],
                "x_dir": [number(v) for v in self.x_dir],
                "y_dir": [number(v) for v in self.y_dir],
            }
        }

    def to_world(self, point: Point2) -> Point3:
        x, y = point
        return tuple(
            o + x * a + y * b for o, a, b in zip(self.origin, self.x_dir, self.y_dir, strict=True)
        )  # type: ignore[return-value]


class Script:
    """An ordered command list with names that stay unique.

    SolidCraft resolves a feature name to its first match and silently renames a repeated body
    name, so a repeat would make later steps act on the wrong thing; `add` refuses repeats.
    """

    def __init__(self) -> None:
        self.commands: list[Json] = []
        self._names: set[str] = set()
        self._bodies: set[str] = set()

    def add(self, command: str, /, **params: Any) -> Json:
        if "name" in params and command.startswith(NAMED_PREFIXES):
            self._claim(params["name"], self._names, "a sketch or feature")
        if "body_name" in params:
            self._claim(params["body_name"], self._bodies, "a body")
        step = {"command": command, "params": clean(params)}
        self.commands.append(step)
        return step

    def extend(self, commands: Sequence[Json]) -> None:
        for step in commands:
            self.add(step["command"], **step.get("params", {}))

    def unique(self, stem: str) -> str:
        """`stem`, or `stem` with the lowest suffix that no sketch, feature or body uses yet."""
        taken = self._names | self._bodies
        if stem not in taken:
            return stem
        index = 2
        while f"{stem}{index}" in taken:
            index += 1
        return f"{stem}{index}"

    def parameter(
        self,
        name: str,
        expression: str | float,
        unit: str | None = None,
        comment: str = "",
    ) -> None:
        """A user parameter; unit "" makes a unitless one such as a count."""
        params: Json = {"name": name, "expression": str(expression)}
        if unit is not None:
            params["unit"] = unit
        if comment:
            params["comment"] = comment
        self.add("parameters.add", **params)

    @contextmanager
    def sketch(self, name: str, plane: Plane | None = None) -> Iterator[Sketch]:
        self.add("sketch.create", name=name, **(plane or Plane()).params())
        yield Sketch(self, name, plane or Plane())
        self.add("sketch.finish")

    def group(self, name: str, features: Sequence[str]) -> None:
        """Fold timeline features into one timeline folder."""
        if features:
            self.add("timeline.group", name=name, features=list(features))

    def to_json(self) -> Json:
        return {"commands": self.commands}

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_json(), indent=1) + "\n")

    @staticmethod
    def _claim(name: str, taken: set[str], kind: str) -> None:
        if name in taken:
            raise ValueError(f"{name}: {kind} already has this name")
        taken.add(name)


class Sketch:
    """Draws into the sketch being edited and predicts the ids SolidCraft gives the curves.

    Each sketch numbers lines, arcs and circles separately from 1, in creation order.
    """

    def __init__(self, script: Script, name: str, plane: Plane) -> None:
        self.script = script
        self.name = name
        self.plane = plane
        self._counts = {"l": 0, "a": 0, "c": 0}

    def _next(self, kind: str) -> str:
        self._counts[kind] += 1
        return f"{kind}{self._counts[kind]}"

    def line(self, start: Point2, end: Point2) -> str:
        self.script.add("sketch.line", points=[list(start), list(end)])
        return self._next("l")

    def polyline(self, points: Sequence[Point2], closed: bool = True) -> list[str]:
        self.script.add("sketch.line", points=[list(p) for p in points], closed=closed)
        return [self._next("l") for _ in range(len(points) if closed else len(points) - 1)]

    def arc(self, arc: Arc) -> str:
        self.script.add(
            "sketch.arc.three_point",
            start=list(arc.start),
            through=list(arc.midpoint),
            end=list(arc.end),
        )
        return self._next("a")

    def circle(self, circle: Circle) -> str:
        self.script.add("sketch.circle.center", center=list(circle.center), radius=circle.radius)
        return self._next("c")

    def rounded_rectangle(self, rect: RoundedRect) -> list[str]:
        """Sides bottom, right, top, left, then corner arcs from bottom-left counter-clockwise."""
        if rect.radius <= 0:
            return self.rectangle(rect)
        if not rect.rounded:
            return self.segments(rect.segments())
        x0, y0, x1, y1 = rect.bounds
        self.script.add("sketch.rectangle.rounded", p0=[x0, y0], p1=[x1, y1], radius=rect.radius)
        lines = [self._next("l") for _ in range(4)]
        return lines + [self._next("a") for _ in range(4)]

    def rectangle(self, rect: RoundedRect) -> list[str]:
        x0, y0, x1, y1 = rect.bounds
        self.script.add("sketch.rectangle.two_point", p0=[x0, y0], p1=[x1, y1])
        return [self._next("l") for _ in range(4)]

    def segments(self, segments: Sequence[Segment]) -> list[str]:
        ids = []
        for segment in segments:
            ids.append(
                self.line(segment.start, segment.end)
                if isinstance(segment, Line)
                else self.arc(segment)
            )
        return ids

    def shape(self, shape: RoundedRect | Circle | Sequence[Segment]) -> list[str]:
        if isinstance(shape, RoundedRect):
            return self.rounded_rectangle(shape)
        if isinstance(shape, Circle):
            return [self.circle(shape)]
        return self.segments(shape)


def number(value: float) -> float | int:
    """A value rounded for the script: whole numbers as ints, no negative zero."""
    rounded = round(float(value), DECIMALS) + 0.0
    return int(rounded) if rounded.is_integer() else rounded


def clean(value: Any) -> Any:
    """Floats rounded throughout a parameter tree; other values unchanged."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"not a finite number: {value}")
        return number(value)
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    return value
