"""Profiles, outlines and settings, checked without SolidCraft."""

from __future__ import annotations

import json
import math

import pytest

from gridfinity.base import Footprint, gap_points, hole_positions, perimeter_connectors
from gridfinity.box import BinShape
from gridfinity.cli import main, parse_element
from gridfinity.clip import profile
from gridfinity.config import (
    BoxConfig,
    ConfigError,
    Element,
    ElementKind,
    Grid,
    HoleStyle,
    LipStyle,
    Orientation,
    PartKind,
    read,
    write,
)
from gridfinity.profiles import inner_surface
from gridfinity.standard import DEFAULT
from solidcraft_script.loops import Arc, Line, RoundedRect, round_corner
from solidcraft_script.script import Script, number


def close(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> bool:
    return len(a) == len(b) and all(math.dist(p, q) < 1e-9 for p, q in zip(a, b, strict=True))


def test_lip_over_a_thin_wall_follows_the_lip_then_the_wall() -> None:
    surface = inner_surface(DEFAULT.lip, 1.2, 2.275, 20.0)
    expected = [
        (0, 0),
        (2.15, 2.15),
        (2.15, 3.95),
        (2.95, 4.75),
        (2.95, 5.95),
        (1.2, 7.7),
        (1.2, 20),
    ]
    assert close(surface, expected)


def test_a_wall_thicker_than_the_lip_steps_in_at_its_top() -> None:
    surface = inner_surface(DEFAULT.lip, 3.0, 2.275, 20.0)
    assert close(surface, [(0, 0), (2.15, 2.15), (2.15, 2.275), (3.0, 2.275), (3.0, 20)])


def test_no_lip_is_a_flat_rim() -> None:
    assert close(inner_surface(((0.0, 0.0),), 1.2, 0.0, 15.0), [(0, 0), (1.2, 0), (1.2, 15)])


def test_bin_heights_match_the_web_generator() -> None:
    shape = BinShape.of(BoxConfig(grid=Grid(1, 1), units_z=3))
    # Apex 7z + 4.995 rounded r 0.1 between the outer face and the 45 degree slope: the arc's
    # top lies r (cot 22.5 - 1) below the apex; its flat pieces stay within 0.005 of the arc
    arc_top = 21 + 4.995 - 0.1 * (1 / math.tan(math.pi / 8) - 1)
    assert shape.height == pytest.approx(arc_top, abs=0.005)
    assert shape.floor == pytest.approx(5.96)
    assert BinShape.of(BoxConfig(lip=LipStyle.NONE)).height == pytest.approx(21 + 4.85)


def test_rounded_corner_is_tangent_to_both_legs() -> None:
    points = round_corner((0.0, 1.0), (0.0, 0.0), (1.0, 1.0), 0.1, 4)
    reach = 0.1 / math.tan(math.pi / 8)
    assert points[0] == pytest.approx((0.0, reach))
    assert points[-1] == pytest.approx((reach / math.sqrt(2), reach / math.sqrt(2)))
    center = (0.1, reach)
    assert all(math.dist(p, center) == pytest.approx(0.1) for p in points)


def test_split_outline_stays_closed_and_breaks_where_asked() -> None:
    rect = RoundedRect((0.0, 0.0), 83.38, 41.38, 3.75)
    breaks = [(-4.0, -20.69), (4.0, -20.69)]
    loop = rect.segments(breaks)
    assert len(loop) == 10
    for a, b in zip(loop, loop[1:] + loop[:1], strict=True):
        assert math.dist(a.end, b.start) < 1e-9
    assert sum(1 for s in loop if isinstance(s, Line)) == 6
    assert all(s.radius == pytest.approx(3.75) for s in loop if isinstance(s, Arc))


def test_inset_keeps_corners_concentric() -> None:
    rect = RoundedRect((0.0, 0.0), 41.38, 41.38, 3.75).inset(2.95)
    assert (rect.width, rect.radius) == pytest.approx((35.48, 0.8))


def test_corner_holes_take_the_outermost_position_of_each_corner_cell() -> None:
    footprint = Footprint.of(Grid(3, 2), DEFAULT)
    corners = hole_positions(footprint, DEFAULT, HoleStyle.CORNER, 42)
    assert sorted(corners) == sorted([(-55.0, -34.0), (-55.0, 34.0), (55.0, -34.0), (55.0, 34.0)])
    assert len(hole_positions(footprint, DEFAULT, HoleStyle.FULL, 42)) == 24


def test_connectors_bridge_neighbouring_cells_on_the_outline() -> None:
    lines = perimeter_connectors(Footprint.of(Grid(2, 1), DEFAULT))
    # Between the two cells' straight edges, top and bottom: 2 r + gap long
    assert len(lines) == 2
    assert all(line.length == pytest.approx(2 * 3.75 + 0.62) for line in lines)


def test_a_trim_through_the_last_column_narrows_its_feet() -> None:
    footprint = Footprint.of(Grid(2, 1), DEFAULT, size_x=70)
    # The bin keeps the grid's -X edge and ends at 70 mm from it
    assert footprint.outline.bounds[0] == pytest.approx(-42 + 0.31)
    assert footprint.outline.bounds[2] == pytest.approx(-42 + 70)
    assert footprint.columns[1] == pytest.approx((0.31, 28.0))
    whole = [footprint.whole(cell) for cell in footprint.cells()]
    assert whole == [True, False]
    # No magnets in the narrowed foot
    assert len(hole_positions(footprint, DEFAULT, HoleStyle.FULL, 42)) == 4


def test_a_trim_too_close_to_a_grid_line_leaves_an_overhang_without_feet() -> None:
    footprint = Footprint.of(Grid(2, 2), DEFAULT, size_x=46)
    assert len(footprint.columns) == 1
    pieces = perimeter_connectors(footprint)
    # The overhang's corners are the outline's own, and its far side has no foot at all
    assert sum(1 for piece in pieces if isinstance(piece, Arc)) == 2
    right = footprint.outline.bounds[2]
    assert any(
        isinstance(p, Line) and p.start[0] == p.end[0] == pytest.approx(right) for p in pieces
    )
    # Strips between rows reach the overhang, so the underside is one region
    assert len(gap_points(footprint)) == 1


def test_a_bin_trimmed_below_one_foot_is_refused() -> None:
    with pytest.raises(ConfigError):
        Footprint.of(Grid(1, 1), DEFAULT, size_x=5)


def test_clip_profile_matches_the_web_generator() -> None:
    expected = [
        (0, 0), (-2.15, -2.15), (-2.15, -3.8), (-1.05, -3.8), (-1.05, -3.55),
        (-1.45, -3.017), (-1.45, -2.45), (1.45, -2.45), (1.45, -3.017), (1.05, -3.55),
        (1.05, -3.8), (2.15, -3.8), (2.15, -2.15),
    ]  # fmt: skip
    assert close(profile(0.0), expected)


def test_element_text() -> None:
    assert parse_element(ElementKind.SCOOP, "0, 12, 24, y, flip") == Element(
        ElementKind.SCOOP, 0, 12, 24, Orientation.Y, True
    )
    with pytest.raises(ConfigError):
        parse_element(ElementKind.WALL, "1,2")


def test_settings_are_checked() -> None:
    with pytest.raises(ConfigError):
        BoxConfig(units_z=1).validate()
    with pytest.raises(ConfigError):
        BoxConfig(elements=(Element(ElementKind.WALL, 0, 6, 25),)).validate()


def test_settings_survive_a_round_trip(tmp_path) -> None:
    config = BoxConfig(
        grid=Grid(3, 1),
        units_z=6,
        lip=LipStyle.THIN,
        elements=(Element(ElementKind.LEDGE, 0, 12, 36, flip=True),),
    )
    path = tmp_path / "bin.json"
    path.write_text(write(config, PartKind.BOX))
    assert read(path, PartKind.BOX) == config


def test_print_config_reflects_the_options(capsys) -> None:
    assert (
        main(["box", "--units", "3", "2", "--height", "4", "--wall", "12,0,12,y", "--print-config"])
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    assert printed["grid"]["units_x"] == 3 and printed["units_z"] == 4
    assert printed["elements"] == [
        {"kind": "wall", "x": 12, "y": 0, "length": 12, "orientation": "y", "flip": False}
    ]


def test_script_refuses_repeated_names() -> None:
    script = Script()
    script.add("solid.box", length=1, width=1, height=1, name="A", body_name="A")
    with pytest.raises(ValueError):
        script.add("solid.box", length=1, width=1, height=1, name="A")
    assert number(1.0000000001) == 1 and number(-0.0) == 0
