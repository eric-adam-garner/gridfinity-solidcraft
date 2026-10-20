"""Dimensions of the Gridfinity system as these parts are built (mm, Z up, z = 0 under the feet).

Profiles are lists of `(inset, depth)` steps: `inset` is measured inward from the outline the
profile runs around, `depth` downward from where the profile starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

type Profile = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Standard:
    height_unit: float = 7.0
    # Total gap between neighbouring bins on a grid, so half of it on each side of a bin
    clearance: float = 0.62
    corner_radius: float = 3.75
    # Foot, from its top edge down: 45 degree flare, straight, 45 degree chamfer
    foot: Profile = ((0.0, 0.0), (2.15, 2.15), (2.15, 3.95), (2.95, 4.75))
    floor_thickness: float = 1.21
    # Stacking lip from its apex on the outer face down to where it meets the outer face again
    lip: Profile = (
        (0.0, 0.0),
        (2.15, 2.15),
        (2.15, 3.95),
        (2.95, 4.75),
        (2.95, 5.95),
        (0.0, 8.9),
    )
    thin_lip: Profile = ((0.0, 0.0), (1.95, 1.95), (1.95, 3.75), (0.0, 5.7))
    # Above `height_unit * units`: the lip apex, the top of a bin without a lip, the top of the
    # outer wall under a lip
    lip_apex: float = 4.995
    rim_top: float = 4.85
    wall_top: float = 2.72
    lip_fillet: float = 0.1
    # Straight pieces that stand in for the apex fillet's arc
    lip_fillet_segments: int = 4
    # Holes under the feet, centred `(pitch - hole_inset) / 2` from a cell's centre on both axes.
    # Each is a cylinder of the magnet's height, or of the screw length, that starts
    # `hole_lead` below the foot, so the hole is that much shallower
    hole_inset: float = 16.0
    hole_lead: float = 0.25
    screw_radius: float = 1.5
    screw_length: float = 4.75
    # Walls, ledges and scoops snap to this many divisions of a grid unit
    subdivisions: int = 12
    element_base: float = 5.95
    ledge_width: float = 15.0
    ledge_depth: float = 15.0
    ledge_depth_short: float = 8.0
    scoop_width: float = 15.0
    scoop_height: float = 13.9
    scoop_height_short: float = 9.9
    # Bins lower than this get the short ledge and scoop
    short_units: int = 3
    baseplate: BaseplateStandard = field(default_factory=lambda: BaseplateStandard())

    @property
    def foot_height(self) -> float:
        return self.foot[-1][1]

    @property
    def foot_inset(self) -> float:
        return self.foot[-1][0]

    @property
    def floor_top(self) -> float:
        return self.foot_height + self.floor_thickness

    def hole_offset(self, pitch: float) -> float:
        return (pitch - self.hole_inset) / 2


@dataclass(frozen=True)
class BaseplateStandard:
    corner_radius: float = 4.0
    # Pocket wall from the top edge on the grid line down
    pocket: Profile = ((0.0, 0.0), (2.15, 2.15), (2.15, 3.95), (2.85, 4.65))
    # Extra height under the pockets when the plate carries magnets or screws
    lift: float = 3.0
    # A pad starts `pad_inset` nearer the cell's centre than a bin's hole, and its hole is
    # centred where the pad's rounded inner corner is
    pad_inset: float = 4.0
    pad_size: float = 10.0
    pad_radius: float = 4.5
    screw_diameter: float = 3.5

    @property
    def height(self) -> float:
        return self.pocket[-1][1]


@dataclass(frozen=True)
class ClipStandard:
    """The clip that joins two connectable baseplates, and the slots it snaps into."""

    roof: float = 2.15
    apex_fillet: float = 0.3
    # Slot cross-section on the plate edge, as (inward from the outer face, height) points. Its
    # floor sits below the crease in the pocket wall rather than on it, which a cut cannot
    # resolve, and level with the bottom of the clip
    slot: tuple[tuple[float, float], ...] = (
        (0.0, 6.0),
        (3.0, 6.0),
        (3.0, 0.65),
        (1.0, 0.65),
        (1.0, 1.1),
        (1.3, 1.5),
        (1.3, 2.0),
        (0.0, 2.0),
    )
    slot_depth: float = 2.25
    length_allowance: float = 0.4


DEFAULT = Standard()
CLIP = ClipStandard()


def slot_width(pitch: float) -> float:
    """Length of a connector slot along the plate edge for a grid unit size."""
    for minimum, width in ((35, 20.0), (25, 15.0), (19, 10.0), (14, 5.0)):
        if pitch >= minimum:
            return width
    return 4.0
