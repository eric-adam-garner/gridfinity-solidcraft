"""What a user chooses for each part, with the ranges the generator accepts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from typing import Any

from gridfinity.standard import DEFAULT, Standard

UNIT_SIZE = (12.0, 70.0)
UNITS_XY = (1, 20)
UNITS_Z = (2, 20)
WALL_THICKNESS = (0.4, 3.0)
MAGNET_DIAMETER = (2.0, 8.2)
MAGNET_HEIGHT = (1.0, 4.0)
SCOOP_SHAPE = (0.1, 0.4)
CLIP_TOLERANCE = (-0.05, 0.2)


class PartKind(StrEnum):
    BOX = "box"
    BASEPLATE = "baseplate"
    CLIP = "clip"


class LipStyle(StrEnum):
    DEFAULT = "default"
    THIN = "thin"
    NONE = "none"


class HoleStyle(StrEnum):
    """Which positions under the feet get a hole: none, the outermost one at each corner of the
    part, or all four in every cell."""

    NONE = "none"
    CORNER = "corner"
    FULL = "full"


class ElementKind(StrEnum):
    WALL = "wall"
    LEDGE = "ledge"
    SCOOP = "scoop"


class Orientation(StrEnum):
    X = "x"
    Y = "y"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Element:
    """A wall, ledge or scoop along a line of the subdivided grid.

    `x`, `y` and `length` count subdivisions of a grid unit from the part's -X/-Y corner. An X
    element starts at `x` and runs `length` along +X on the line `y`; a Y element the other way
    round. Ledges and scoops face +Y (X elements) or +X (Y elements), or the other way when
    flipped.
    """

    kind: ElementKind
    x: int
    y: int
    length: int
    orientation: Orientation = Orientation.X
    flip: bool = False

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Element:
        return cls(
            kind=ElementKind(data["kind"]),
            x=int(data["x"]),
            y=int(data["y"]),
            length=int(data["length"]),
            orientation=Orientation(data.get("orientation", "x")),
            flip=bool(data.get("flip", False)),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "x": self.x,
            "y": self.y,
            "length": self.length,
            "orientation": self.orientation.value,
            "flip": self.flip,
        }


@dataclass(frozen=True)
class Grid:
    units_x: int = 2
    units_y: int = 2
    unit_size: float = 42.0

    def validate(self) -> None:
        _range("units_x", self.units_x, UNITS_XY, whole=True)
        _range("units_y", self.units_y, UNITS_XY, whole=True)
        _range("unit_size", self.unit_size, UNIT_SIZE)

    @property
    def width(self) -> float:
        return self.units_x * self.unit_size

    @property
    def depth(self) -> float:
        return self.units_y * self.unit_size

    def cells(self) -> list[tuple[float, float]]:
        """Cell centres, the grid centred on the origin, row by row from -Y."""
        u = self.unit_size
        return [
            ((i - (self.units_x - 1) / 2) * u, (j - (self.units_y - 1) / 2) * u)
            for j in range(self.units_y)
            for i in range(self.units_x)
        ]


@dataclass(frozen=True)
class Holes:
    magnets: HoleStyle = HoleStyle.NONE
    screws: HoleStyle = HoleStyle.NONE
    magnet_diameter: float = 6.2
    magnet_height: float = 2.1

    def validate(self) -> None:
        _range("magnet_diameter", self.magnet_diameter, MAGNET_DIAMETER)
        _range("magnet_height", self.magnet_height, MAGNET_HEIGHT)

    @property
    def any(self) -> bool:
        return self.magnets != HoleStyle.NONE or self.screws != HoleStyle.NONE


@dataclass(frozen=True)
class BoxConfig:
    grid: Grid = field(default_factory=Grid)
    units_z: int = 3
    lip: LipStyle = LipStyle.DEFAULT
    holes: Holes = field(default_factory=Holes)
    outer_wall: float = 1.2
    inner_wall: float = 0.8
    scoop_shape: float = 0.4
    elements: tuple[Element, ...] = ()
    # Trim the bin to this size (mm) on its +X/+Y sides; None keeps the whole grid
    size_x: float | None = None
    size_y: float | None = None
    # Build the top of the bin, above a cut just below the top, as a body of its own
    split_top: bool = False
    standard: Standard = DEFAULT

    def validate(self) -> None:
        self.grid.validate()
        self.holes.validate()
        _sizes(self.grid, self.size_x, self.size_y)
        _range("units_z", self.units_z, UNITS_Z, whole=True)
        _range("outer_wall", self.outer_wall, WALL_THICKNESS)
        _range("inner_wall", self.inner_wall, WALL_THICKNESS)
        _range("scoop_shape", self.scoop_shape, SCOOP_SHAPE)
        n = self.standard.subdivisions
        for index, element in enumerate(self.elements):
            limit_x, limit_y = n * self.grid.units_x, n * self.grid.units_y
            along, span = (
                (element.x, limit_x)
                if element.orientation == Orientation.X
                else (element.y, limit_y)
            )
            if not (0 <= element.x <= limit_x and 0 <= element.y <= limit_y):
                raise ConfigError(f"element {index}: ({element.x}, {element.y}) is off the grid")
            if element.length < 1 or along + element.length > span:
                raise ConfigError(f"element {index}: length {element.length} runs off the grid")


@dataclass(frozen=True)
class BaseplateConfig:
    grid: Grid = field(default_factory=Grid)
    holes: Holes = field(default_factory=Holes)
    connectable: bool = False
    # Trim the plate to this size (mm) on its +X/+Y sides; None keeps the whole grid
    size_x: float | None = None
    size_y: float | None = None
    standard: Standard = DEFAULT

    def validate(self) -> None:
        self.grid.validate()
        self.holes.validate()
        _sizes(self.grid, self.size_x, self.size_y)


@dataclass(frozen=True)
class ClipConfig:
    unit_size: float = 42.0
    tolerance: float = 0.0

    def validate(self) -> None:
        _range("unit_size", self.unit_size, UNIT_SIZE)
        _range("tolerance", self.tolerance, CLIP_TOLERANCE)


type PartConfig = BoxConfig | BaseplateConfig | ClipConfig

KINDS: dict[PartKind, type] = {
    PartKind.BOX: BoxConfig,
    PartKind.BASEPLATE: BaseplateConfig,
    PartKind.CLIP: ClipConfig,
}


def read(path: Path, kind: PartKind) -> PartConfig:
    """Settings for one kind of part from a JSON file of config fields; a `kind` field, if
    present, must match."""
    data = json.loads(Path(path).read_text())
    if data.pop("kind", kind.value) != kind.value:
        raise ConfigError(f"{path} describes another kind of part")
    return from_json(KINDS[kind], data)


def write(config: PartConfig, kind: PartKind) -> str:
    """Settings as the JSON that `read` takes."""
    return json.dumps({"kind": kind.value, **to_json(config)}, indent=2) + "\n"


def from_json[T](cls: type[T], data: Mapping[str, Any]) -> T:
    """A config dataclass from plain JSON values; nested configs and enums by field type."""
    known = {f.name: f for f in fields(cls)}  # type: ignore[arg-type]
    unknown = set(data) - set(known)
    if unknown:
        raise ConfigError(f"{cls.__name__}: unknown fields {sorted(unknown)}")
    values: dict[str, Any] = {}
    for name, value in data.items():
        values[name] = _convert(name, value)
    return cls(**values)


def to_json(config: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields(config):
        value = getattr(config, f.name)
        if f.name == "standard":
            continue
        if isinstance(value, StrEnum):
            out[f.name] = value.value
        elif isinstance(value, tuple):
            out[f.name] = [v.to_json() for v in value]
        elif hasattr(value, "__dataclass_fields__"):
            out[f.name] = to_json(value)
        else:
            out[f.name] = value
    return out


def _convert(name: str, value: Any) -> Any:
    nested = {
        "grid": Grid,
        "holes": Holes,
    }
    enums = {
        "lip": LipStyle,
        "magnets": HoleStyle,
        "screws": HoleStyle,
    }
    if name in nested:
        return from_json(nested[name], value)
    if name in enums:
        return enums[name](value)
    if name == "elements":
        return tuple(Element.from_json(item) for item in value)
    if name == "standard":
        raise ConfigError("the standard is not read from JSON")
    return value


def _sizes(grid: Grid, size_x: float | None, size_y: float | None) -> None:
    """A trimmed size cuts into the last unit of the grid and no further."""
    for name, size, units in (("size_x", size_x, grid.units_x), ("size_y", size_y, grid.units_y)):
        if size is None:
            continue
        u = grid.unit_size
        low, high = (units - 1) * u + 1, units * u
        if not low <= size <= high:
            raise ConfigError(f"{name} = {size} must lie in {low:g}..{high:g} for {units} units")


def _range(name: str, value: float, bounds: tuple[float, float], whole: bool = False) -> None:
    low, high = bounds
    if whole and value != int(value):
        raise ConfigError(f"{name} = {value} must be a whole number")
    if not low <= value <= high:
        raise ConfigError(f"{name} = {value} must lie in {low:g}..{high:g}")
