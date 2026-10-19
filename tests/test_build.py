"""Parts built headless with solidcraft-cli, measured against volumes worked out by hand."""

from __future__ import annotations

import math

import pytest
from oracle import baseplate_volume, bin_volume, polygon_area

from gridfinity.baseplate import build_baseplate
from gridfinity.box import build_box
from gridfinity.cli import main
from gridfinity.clip import build_clip, profile
from gridfinity.config import (
    BaseplateConfig,
    BoxConfig,
    ClipConfig,
    Element,
    ElementKind,
    Grid,
    Holes,
    HoleStyle,
    LipStyle,
    Orientation,
)
from solidcraft_script.runner import Body, available, run

pytestmark = [
    pytest.mark.solidcraft,
    pytest.mark.skipif(not available(), reason="solidcraft-cli is not on PATH"),
]

# SolidCraft measures volumes to about 0.01%; the lip's apex fillet, built from four flat
# pieces, differs from the arc by far less than that
EXACT = 1e-4


def single(commands: list, retries: int = 0) -> Body:
    """The one body the commands build, in one closed shell, with at most `retries` features
    that needed a looser tolerance."""
    result = run(commands)
    assert len(result.problems) <= retries, result.problems
    assert all("Boolean retry" in p for p in result.problems), result.problems
    bodies = result.bodies
    assert len(bodies) == 1 and bodies[0].shells == 1
    return bodies[0]


@pytest.mark.parametrize(
    ("units", "lip"),
    [((1, 1, 3), LipStyle.DEFAULT), ((3, 2, 2), LipStyle.DEFAULT), ((2, 2, 4), LipStyle.THIN)],
)
def test_bin(units: tuple[int, int, int], lip: LipStyle) -> None:
    x, y, z = units
    body = single(build_box(BoxConfig(grid=Grid(x, y), units_z=z, lip=lip)).commands)
    assert body.volume == pytest.approx(bin_volume(x, y, z, lip.value), rel=EXACT)
    assert body.size[:2] == pytest.approx((42 * x - 0.62, 42 * y - 0.62), abs=1e-3)


@pytest.mark.parametrize(
    ("units", "size"),
    [
        # The cut column keeps a narrower foot
        ((2, 1, 3), (70.0, 42.0)),
        # Too little is left past the first column for a foot: the floor overhangs
        ((2, 2, 3), (46.0, 84.0)),
        # Trimmed both ways in a single cell
        ((1, 1, 4), (30.0, 25.0)),
    ],
)
def test_trimmed_bin(units: tuple[int, int, int], size: tuple[float, float]) -> None:
    x, y, z = units
    config = BoxConfig(grid=Grid(x, y), units_z=z, size_x=size[0], size_y=size[1])
    body = single(build_box(config).commands)
    assert body.volume == pytest.approx(bin_volume(x, y, z, size=size), rel=EXACT)
    # The bin keeps the grid's -X/-Y corner and ends at the size on the other sides
    assert body.bbox_min[:2] == pytest.approx((-21 * x + 0.31, -21 * y + 0.31), abs=1e-3)
    assert body.bbox_max[0] == pytest.approx(-21 * x + min(size[0], 42 * x - 0.31), abs=1e-3)


def test_bin_without_lip_with_magnets_and_screws() -> None:
    holes = Holes(magnets=HoleStyle.FULL, screws=HoleStyle.FULL)
    config = BoxConfig(grid=Grid(2, 1), lip=LipStyle.NONE, holes=holes)
    # Magnet pockets as deep as the magnet, screw holes on to 4.5 mm
    drilled = 8 * (math.pi * 3.1**2 * 2.1 + math.pi * 1.5**2 * (4.5 - 2.1))
    body = single(build_box(config).commands)
    assert body.volume == pytest.approx(bin_volume(2, 1, 3, "none", holes=drilled), rel=EXACT)
    assert body.size[2] == pytest.approx(21 + 4.85, abs=1e-3)


def test_corner_magnets_only_drill_four() -> None:
    config = BoxConfig(grid=Grid(2, 2), lip=LipStyle.NONE, holes=Holes(magnets=HoleStyle.CORNER))
    body = single(build_box(config).commands)
    drilled = 4 * math.pi * 3.1**2 * 2.1
    assert body.volume == pytest.approx(bin_volume(2, 2, 3, "none", holes=drilled), rel=EXACT)


def test_interior_wall_adds_what_shows_inside() -> None:
    plain = single(build_box(BoxConfig(grid=Grid(2, 1))).commands).volume
    walled = BoxConfig(grid=Grid(2, 1), elements=(Element(ElementKind.WALL, 0, 6, 24),))
    added = single(build_box(walled).commands).volume - plain
    # 0.8 thick across the cavity, whose span narrows at the lip: 1.2 in up to z 18.295, out
    # to 2.95 by z 20.045, then 2.95 to the wall's top at z 21
    span = 83.38
    shown = (span - 2.4) * 12.335 + (span - 2 * 2.075) * 1.75 + (span - 5.9) * 0.955
    assert added == pytest.approx(0.8 * shown, rel=EXACT)


def test_every_element_kind_builds() -> None:
    elements = (
        Element(ElementKind.WALL, 12, 0, 12, Orientation.Y),
        Element(ElementKind.SCOOP, 0, 0, 24),
        Element(ElementKind.LEDGE, 0, 12, 24, flip=True),
    )
    # A scoop's curve meets the floor almost tangentially, which the join resolves on a retry
    body = single(build_box(BoxConfig(grid=Grid(2, 1), elements=elements)).commands, retries=1)
    assert body.volume > bin_volume(2, 1, 3)


def test_interior_scoop_adds_its_cove() -> None:
    plain = single(build_box(BoxConfig(grid=Grid(2, 1))).commands).volume
    scooped = BoxConfig(grid=Grid(2, 1), elements=(Element(ElementKind.SCOOP, 0, 6, 24),))
    added = single(build_box(scooped).commands, retries=1).volume - plain
    assert added == pytest.approx(scoop_volume(), rel=5e-4)


def scoop_volume() -> float:
    """A scoop on the middle line of a 2x1x3 bin, worked out from the web generator's drawing:
    a back 0.4 thick (half an inner wall) up to z 20.8, and a cove from 15 mm out up to 13.9 mm
    high on the back, bulging 0.4 half-chords toward the corner. The cove starts 0.05 above the
    floor (z 5.96), on a strip as wide as the scoop."""
    back, base, top = 0.4, 6.01, 20.8
    foot, head = (back + 15, 0.0), (back, 13.9)
    chord = math.dist(foot, head)
    sagitta = 0.4 * chord / 2
    radius = (chord**2 / 4 + sagitta**2) / (2 * sagitta)
    mid = ((foot[0] + head[0]) / 2, (foot[1] + head[1]) / 2)
    normal = (-(head[1] - foot[1]) / chord, (head[0] - foot[0]) / chord)  # toward the corner
    centre = (mid[0] - normal[0] * (radius - sagitta), mid[1] - normal[1] * (radius - sagitta))

    def width(z: float) -> float:
        """How far out from the line the scoop reaches at height z."""
        v = z - base
        if v < 0:
            return foot[0]
        if v >= head[1]:
            return back
        # The cove surface: the circle's lower-left part, between foot and head
        return centre[0] - math.sqrt(radius**2 - (v - centre[1]) ** 2)

    def span(z: float) -> float:
        """Length of the scoop shown inside the cavity at height z."""
        inset = 1.2 if z <= 18.295 else min(2.95, 1.2 + (z - 18.295))
        return 83.38 - 2 * inset

    steps = 20000
    floor = 5.96
    dz = (top - floor) / steps
    heights = (floor + (k + 0.5) * dz for k in range(steps))
    return sum(width(z) * span(z) * dz for z in heights)


def test_edge_ledge_reaches_into_the_corners() -> None:
    config = BoxConfig(
        grid=Grid(3, 2), units_z=6, elements=(Element(ElementKind.LEDGE, 0, 24, 36, flip=True),)
    )
    # Running into the rounded corners makes the join retry, which has gone wrong before
    body = single(build_box(config).commands, retries=1)
    assert body.volume == pytest.approx(bin_volume(3, 2, 6) + edge_ledge_volume(), rel=EXACT)


def edge_ledge_volume() -> float:
    """What a full-length 15 mm ledge on the back edge of a 3x2x6 bin adds inside it: the
    part of the triangle (top at z 42, sloping 45 degrees down to the outer face at z 27) that
    lies in the cavity, whose rounded corners shrink with the lip's inset."""
    width = 3 * 42 - 0.62

    def inset(z: float) -> float:
        return 1.2 if z <= 39.295 else min(2.95, 1.2 + (z - 39.295))

    def added(z: float) -> float:
        i, reach = inset(z), z - 27.0
        if reach <= i:
            return 0.0
        corner = 3.75 - i
        depth = reach - i
        t = min(depth, corner)
        # Each back corner of the cavity leaves out what lies outside its arc
        n = 400
        gap = sum(
            (corner - math.sqrt(corner**2 - (corner - (k + 0.5) * t / n) ** 2)) * t / n
            for k in range(n)
        )
        return (width - 2 * i) * depth - 2 * gap

    steps = 3000
    dz = 15.0 / steps
    return sum(added(27.0 + (k + 0.5) * dz) * dz for k in range(steps))


@pytest.mark.parametrize(("units", "lift"), [((1, 1), 0.0), ((3, 2), 0.0)])
def test_baseplate(units: tuple[int, int], lift: float) -> None:
    body = single(build_baseplate(BaseplateConfig(grid=Grid(*units))).commands)
    assert body.volume == pytest.approx(baseplate_volume(*units), rel=EXACT)
    assert body.size == pytest.approx((42 * units[0], 42 * units[1], 4.65), abs=1e-3)


def test_baseplate_with_magnets_and_screws() -> None:
    config = BaseplateConfig(
        grid=Grid(2, 1), holes=Holes(magnets=HoleStyle.FULL, screws=HoleStyle.FULL)
    )
    # Magnet pockets from the pad tops, screw holes on through the 3 mm pads
    drilled = 8 * (math.pi * 3.1**2 * 2.1 + math.pi * 1.75**2 * (3 - 2.1))
    body = single(build_baseplate(config).commands)
    assert body.volume == pytest.approx(baseplate_volume(2, 1, 3.0, drilled), rel=EXACT)


def test_connectable_baseplate_cuts_a_slot_per_edge_unit() -> None:
    plain = baseplate_volume(2, 2)
    body = single(build_baseplate(BaseplateConfig(grid=Grid(2, 2), connectable=True)).commands)
    assert 0 < plain - body.volume < 8 * 20 * 2.25 * 4.65


def test_trimmed_baseplate_is_cut_to_size() -> None:
    body = single(build_baseplate(BaseplateConfig(grid=Grid(3, 2), size_x=110, size_y=70)).commands)
    assert body.size == pytest.approx((110, 70, 4.65), abs=1e-3)
    assert body.bbox_min[:2] == pytest.approx((-63, -42), abs=1e-3)


def test_clip() -> None:
    body = single(build_clip(ClipConfig()).commands)
    length = 20 - 0.4
    # The apex fillet takes r^2 (cot 45 - pi/4) off the right-angled roof along the length
    expected = (polygon_area(profile(0.0)) - 0.3**2 * (1 - math.pi / 4)) * length
    assert body.volume == pytest.approx(expected, rel=EXACT)


def test_command_line_writes_files(tmp_path) -> None:
    stl, step = tmp_path / "bin.stl", tmp_path / "bin.step"
    assert (
        main(["box", "--units", "1", "1", "--height", "2", "--out", str(stl), "--out", str(step)])
        == 0
    )
    assert stl.stat().st_size > 10_000
    assert step.read_text().startswith("ISO-10303-21")
