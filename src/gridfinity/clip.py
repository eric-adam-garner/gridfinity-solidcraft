"""The clip that joins two connectable baseplates: it drops into the slots facing each other
across the seam and snaps around the ribs below them."""

from __future__ import annotations

from gridfinity.config import ClipConfig
from gridfinity.standard import CLIP, ClipStandard, slot_width
from solidcraft_script.loops import Point2
from solidcraft_script.script import Plane, Script

BODY = "Clip"
# Below the roof: each leg's straight drop, then its foot inward, the foot's rise, the barb's
# slope (rise and outward step) and the rise to the crossbar
BARB_RISE = 0.533
BARB_STEP = 0.4
LEG = 1.65
FOOT = 1.1
FOOT_RISE = 0.25
BARB_TOP = 0.567


def profile(tolerance: float, std: ClipStandard = CLIP) -> list[Point2]:
    """The clip's cross-section with its apex at the origin, counter-clockwise from the apex.

    A positive tolerance opens the gap between the legs and their barbs.
    """
    roof = std.roof
    foot = FOOT - tolerance
    foot_rise = FOOT_RISE - tolerance
    barb_top = BARB_TOP + 2 * tolerance
    left = [(0.0, 0.0), (-roof, -roof), (-roof, -roof - LEG)]
    x, y = left[-1]
    for dx, dy in ((foot, 0.0), (0.0, foot_rise), (-BARB_STEP, BARB_RISE), (0.0, barb_top)):
        x, y = x + dx, y + dy
        left.append((x, y))
    # The crossbar joins the left half to its mirror image
    return left + [(-px, py) for px, py in reversed(left[1:])]


def build_clip(config: ClipConfig, script: Script | None = None) -> Script:
    config.validate()
    script = script or Script()
    points = profile(config.tolerance)
    depth = -min(y for _, y in points)
    length = slot_width(config.unit_size) - CLIP.length_allowance
    # Sketch x runs along -X so that the extrusion points along +Y; the profile is symmetric
    plane = Plane((0.0, -length / 2, depth), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    with script.sketch("ClipSection", plane) as sketch:
        sketch.polyline(points, closed=True)
    script.add("solid.extrude", sketch="ClipSection", distance=length, name=BODY, body_name=BODY)
    script.add(
        "solid.fillet", edges=[[0.0, 0.0, depth]], radius=CLIP.apex_fillet, name="ApexFillet"
    )
    script.add("browser.visibility", visible=False, folder="sketches")
    return script
