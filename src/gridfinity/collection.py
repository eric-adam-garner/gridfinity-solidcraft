"""Collections: several parts laid out on one grid inside a bounding volume, such as a drawer.

Each part is built and saved as its own design; the collection is a design holding a linked
component of each, moved to its grid position and turned by its rotation.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gridfinity.config import (
    KINDS,
    UNIT_SIZE,
    BaseplateConfig,
    BoxConfig,
    ClipConfig,
    ConfigError,
    PartConfig,
    PartKind,
    from_json,
    to_json,
)
from solidcraft_script.script import Script

ROTATIONS = (0, 90, 180, 270)
# Height a part claims in the collection, by kind, in height units for a baseplate
BASEPLATE_UNITS = 1
LIP_ALLOWANCE = 4.4


@dataclass(frozen=True)
class Item:
    """A part placed at whole cells `x`, `y` of the collection's grid and `z` height units up,
    turned `rotation` degrees about its own centre."""

    name: str
    kind: PartKind
    part: PartConfig
    x: int = 0
    y: int = 0
    z: int = 0
    rotation: int = 0

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Item:
        part = dict(data["part"])
        kind = PartKind(part.pop("kind"))
        rotation = int(data.get("rotation", 0))
        if rotation not in ROTATIONS:
            raise ConfigError(f"{data['name']}: rotation must be one of {ROTATIONS}")
        return cls(
            name=str(data["name"]),
            kind=kind,
            part=from_json(KINDS[kind], part),
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            z=0 if kind == PartKind.BASEPLATE else int(data.get("z", 0)),
            rotation=rotation,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "rotation": self.rotation,
            "part": {"kind": self.kind.value, **to_json(self.part)},
        }


@dataclass(frozen=True)
class CollectionConfig:
    unit_size: float = 42.0
    # Width, depth and height of the space the parts must fit in, mm
    bounds: tuple[float, float, float] = (300.0, 300.0, 100.0)
    items: tuple[Item, ...] = field(default_factory=tuple)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> CollectionConfig:
        unknown = set(data) - {"kind", "unit_size", "bounds", "items"}
        if unknown:
            raise ConfigError(f"collection: unknown fields {sorted(unknown)}")
        items = tuple(Item.from_json(item) for item in data.get("items", ()))
        names = [item.name for item in items]
        if len(set(names)) != len(names):
            raise ConfigError("collection: item names must be unique")
        return cls(
            unit_size=float(data.get("unit_size", 42.0)),
            bounds=tuple(float(v) for v in data.get("bounds", (300, 300, 100))),  # type: ignore[arg-type]
            items=items,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "collection",
            "unit_size": self.unit_size,
            "bounds": list(self.bounds),
            "items": [item.to_json() for item in self.items],
        }

    def validate(self) -> None:
        low, high = UNIT_SIZE
        if not low <= self.unit_size <= high:
            raise ConfigError(f"unit_size = {self.unit_size} must lie in {low:g}..{high:g}")
        for item in self.items:
            item.part.validate()


@dataclass(frozen=True)
class Placement:
    item: Item
    # Centre of the part's footprint and the height of its underside, mm
    center: tuple[float, float, float]
    # Cells the part covers: x and y on the collection's grid, z in height units
    cells: tuple[range, range, range]


def read(path: Path) -> CollectionConfig:
    data = json.loads(Path(path).read_text())
    if data.get("kind", "collection") != "collection":
        raise ConfigError(f"{path} does not describe a collection")
    return CollectionConfig.from_json(data)


def footprint(item: Item) -> tuple[float, float, float]:
    """Width, depth (before rotation) and nominal height of a part, mm."""
    part = item.part
    if isinstance(part, ClipConfig):
        return (part.unit_size, part.unit_size, part.unit_size)
    grid = part.grid
    if isinstance(part, BaseplateConfig):
        width = part.size_x if part.size_x is not None else grid.width
        depth = part.size_y if part.size_y is not None else grid.depth
        return (width, depth, BASEPLATE_UNITS * part.standard.height_unit)
    assert isinstance(part, BoxConfig)
    height = part.units_z * part.standard.height_unit + LIP_ALLOWANCE
    return (grid.width, grid.depth, height)


def item_unit(item: Item) -> float:
    part = item.part
    return part.unit_size if isinstance(part, ClipConfig) else part.grid.unit_size


def place(config: CollectionConfig) -> tuple[list[Placement], list[str]]:
    """Where each part goes, and every problem the layout has: parts out of bounds, parts that
    claim the same cell, grid units that do not match the collection's."""
    width, depth, height = config.bounds
    unit = config.unit_size
    height_unit = 7.0
    placements: list[Placement] = []
    problems: list[str] = []
    for item in config.items:
        own = item_unit(item)
        if abs(own - unit) > 1e-9:
            problems.append(
                f"{item.name}: its grid unit {own:g} mm differs from the collection's {unit:g} mm"
            )
        # A part steps by its own unit where that divides the collection's
        ratio = unit / own
        step = own if abs(ratio - round(ratio)) < 1e-9 else unit
        fx, fy, fz = footprint(item)
        if item.rotation in (90, 270):
            fx, fy = fy, fx
        x0 = -width / 2 + item.x * step
        y0 = -depth / 2 + item.y * step
        z0 = item.z * height_unit
        center = (x0 + fx / 2, y0 + fy / 2, z0)
        cells = (
            range(
                math.floor(item.x * step / unit + 1e-9),
                math.ceil((item.x * step + fx) / unit - 1e-9),
            ),
            range(
                math.floor(item.y * step / unit + 1e-9),
                math.ceil((item.y * step + fy) / unit - 1e-9),
            ),
            range(item.z, item.z + math.ceil(fz / height_unit - 1e-9)),
        )
        if (
            x0 < -width / 2 - 1e-9
            or y0 < -depth / 2 - 1e-9
            or x0 + fx > width / 2 + 1e-9
            or y0 + fy > depth / 2 + 1e-9
            or z0 + fz > height + 1e-9
        ):
            problems.append(f"{item.name}: lies outside the collection's bounds")
        placements.append(Placement(item, center, cells))
    problems += _overlaps(placements)
    return placements, problems


def _overlaps(placements: Sequence[Placement]) -> list[str]:
    """Baseplates collide with baseplates on the grid; every other part with every other part
    in grid cells and height units."""
    problems = []
    for index, a in enumerate(placements):
        for b in placements[index + 1 :]:
            plates = (a.item.kind == PartKind.BASEPLATE, b.item.kind == PartKind.BASEPLATE)
            if plates[0] != plates[1]:
                continue
            axes = 2 if plates[0] else 3
            if all(set(a.cells[k]) & set(b.cells[k]) for k in range(axes)):
                problems.append(f"{a.item.name} and {b.item.name} claim the same cells")
    return problems


def assemble(
    placements: Sequence[Placement], designs: Mapping[str, Path], script: Script | None = None
) -> Script:
    """The collection design: a linked component of each part's saved design, placed."""
    script = script or Script()
    for placement in placements:
        item = placement.item
        cx, cy, z = placement.center
        script.add(
            "component.insert_design",
            path=str(designs[item.name]),
            name=item.name,
            translate=[cx, cy, z],
        )
        if item.rotation:
            script.add(
                "occurrence.move",
                # An inserted design is placed once, as the first occurrence of its component
                occurrence=f"{item.name}:1",
                space="world",
                axis=[0, 0, 1],
                angle=f"{item.rotation} deg",
                origin=[cx, cy, z],
            )
    return script
