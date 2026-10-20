"""Bins: feet on the grid, a floor, an outer wall with a stacking lip, and walls, ledges and
scoops placed inside."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from gridfinity.base import Footprint, add_feet
from gridfinity.config import BoxConfig, LipStyle
from gridfinity.elements import add_elements
from gridfinity.profiles import inner_surface, simplify
from gridfinity.standard import Profile, Standard
from solidcraft_script.loops import RoundedRect, round_corner
from solidcraft_script.script import Script
from solidcraft_script.shells import ShellBuilder, split_wall, sweep_profile

BODY = "Bin"
TOP_BODY = "BinTop"


@dataclass(frozen=True)
class BinShape:
    """Heights and outlines of a bin, from which its faces and its elements are placed."""

    outline: RoundedRect
    floor: float
    wall: float
    # Where walls, ledges and scoops end: a whole number of height units
    nominal: float
    # The inside of the outer wall, from the top of the outer face down to the floor, as
    # (inset, z) points
    inner: tuple[tuple[float, float], ...]

    @staticmethod
    def of(config: BoxConfig, floor: float | None = None) -> BinShape:
        std = config.standard
        nominal = config.units_z * std.height_unit
        floor = std.floor_top if floor is None else max(floor, std.floor_top)
        lip = lip_profile(std, config.lip)
        if lip is None:
            top = nominal + std.rim_top
            surface = inner_surface(((0.0, 0.0),), config.outer_wall, 0.0, top - floor)
        else:
            top = nominal + std.lip_apex
            surface = inner_surface(
                lip, config.outer_wall, std.lip_apex - std.wall_top, top - floor
            )
            # The apex: the outer face (straight down from it) meets the lip's first slope
            apex = round_corner(
                (0.0, 1.0), surface[0], surface[1], std.lip_fillet, std.lip_fillet_segments
            )
            surface = [*apex, *surface[1:]]
        return BinShape(
            outline=footprint(config).outline,
            floor=floor,
            wall=config.outer_wall,
            nominal=nominal,
            inner=tuple((inset, top - depth) for inset, depth in surface),
        )

    @property
    def rim(self) -> float:
        """Top of the outer face."""
        return self.inner[0][1]

    @property
    def height(self) -> float:
        return max(z for _, z in self.inner)

    def cut(self, z: float) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """The inside of the wall above and below height `z`, each closed across the wall by
        a flat ring at `z`: above, from the top down to the ring; below, from the ring down to
        the floor."""
        for index, ((i0, z0), (i1, z1)) in enumerate(pairwise(self.inner)):
            if z0 - z1 > 1e-9 and z1 - 1e-9 <= z <= z0 + 1e-9:
                inset = i0 + (i1 - i0) * (z0 - z) / (z0 - z1)
                upper = [*self.inner[: index + 1], (inset, z), (0.0, z)]
                lower = [(0.0, z), (inset, z), *self.inner[index + 1 :]]
                return simplify(upper), simplify(lower)
        raise ValueError(f"the inside of the wall does not reach height {z:g}")

    def inset_at(self, z: float) -> float:
        """How far in from the outline the inside of the wall lies at height `z`; the outer
        wall's thickness below the floor."""
        for (i0, z0), (i1, z1) in pairwise(self.inner):
            low, high = min(z0, z1), max(z0, z1)
            if low - 1e-9 <= z <= high + 1e-9:
                if high - low < 1e-9:
                    return max(i0, i1)
                return i0 + (i1 - i0) * (z - z0) / (z1 - z0)
        return self.wall


def footprint(config: BoxConfig) -> Footprint:
    return Footprint.of(config.grid, config.standard, config.size_x, config.size_y)


def lip_profile(std: Standard, style: LipStyle) -> Profile | None:
    return {LipStyle.DEFAULT: std.lip, LipStyle.THIN: std.thin_lip, LipStyle.NONE: None}[style]


def build_box(
    config: BoxConfig, script: Script | None = None, floor: float | None = None
) -> Script:
    """The bin as one body, or as two split just below the top; `floor` raises the inside
    floor to that height."""
    config.validate()
    script = script or Script()
    std = config.standard
    shape = BinShape.of(config, floor)
    if config.split_top:
        # Each part is a closed shell of its own, sharing the flat ring at the cut
        cut = shape.height - std.split_depth
        upper, lower = shape.cut(cut)
    else:
        cut, upper, lower = shape.rim, [], list(shape.inner)
    shell = ShellBuilder(script, BODY)
    splits = add_feet(shell, footprint(config), config.grid, std, config.holes)
    split_wall(shell, shape.outline, std.foot_height, cut, bottom_splits=splits)
    sections = sweep_profile(shell, [shape.outline], lower, kind="Wall")
    shell.patch(sections[len(lower) - 1], [shape.outline.center], kind="Floor")
    shell.stitch()
    if upper:
        top = ShellBuilder(script, TOP_BODY)
        split_wall(top, shape.outline, cut, shape.rim)
        sweep_profile(top, [shape.outline], upper, kind="Lip")
        top.stitch()
    add_elements(script, config, shape, BODY)
    script.add("browser.visibility", visible=False, folder="sketches")
    return script
