"""Collections: where parts land, which layouts are flagged, and an assembled design."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gridfinity.cli import main
from gridfinity.collection import CollectionConfig, place
from solidcraft_script.runner import available, run

EXAMPLE = Path(__file__).parent.parent / "examples" / "drawer.json"


def layout(*items: dict, bounds: tuple[float, float, float] = (168, 168, 60)) -> CollectionConfig:
    return CollectionConfig.from_json(
        {"unit_size": 42, "bounds": list(bounds), "items": list(items)}
    )


def box(x: int, y: int, z: int = 3) -> dict:
    return {"kind": "box", "grid": {"units_x": x, "units_y": y}, "units_z": z}


def test_parts_are_placed_from_the_bounds_corner_by_whole_cells() -> None:
    placements, problems = place(layout({"name": "a", "x": 1, "y": 2, "part": box(2, 1)}))
    assert problems == []
    # Footprint 84 x 42 starting one cell in and two cells up from the corner at (-84, -84)
    assert placements[0].origin == pytest.approx((-84 + 42 + 42, -84 + 84 + 21, 0))


def test_a_quarter_turn_swaps_the_footprint() -> None:
    placements, _ = place(layout({"name": "a", "x": 0, "y": 0, "rotation": 90, "part": box(2, 1)}))
    assert placements[0].origin == pytest.approx((-84 + 21, -84 + 42, 0))
    assert (len(placements[0].cells[0]), len(placements[0].cells[1])) == (1, 2)


def test_overlapping_bins_are_flagged_but_a_bin_on_a_baseplate_is_not() -> None:
    plate = {"kind": "baseplate", "grid": {"units_x": 4, "units_y": 4}}
    _, problems = place(
        layout(
            {"name": "plate", "part": plate},
            {"name": "a", "x": 0, "y": 0, "part": box(2, 2)},
            {"name": "b", "x": 1, "y": 1, "part": box(2, 2)},
        )
    )
    assert problems == ["a and b claim the same cells"]


def test_stacked_bins_only_collide_where_their_heights_meet() -> None:
    # A 3-unit bin claims 4 height units with its lip, so one at z 4 clears it and z 3 does not
    clear = layout(
        {"name": "a", "part": box(1, 1)},
        {"name": "b", "z": 4, "part": box(1, 1)},
        bounds=(168, 168, 100),
    )
    hit = layout(
        {"name": "a", "part": box(1, 1)},
        {"name": "b", "z": 3, "part": box(1, 1)},
        bounds=(168, 168, 100),
    )
    assert place(clear)[1] == []
    assert place(hit)[1] == ["a and b claim the same cells"]


def test_parts_outside_the_bounds_are_flagged() -> None:
    _, problems = place(layout({"name": "big", "x": 2, "y": 0, "part": box(3, 1)}))
    assert problems == ["big: lies outside the collection's bounds"]


def test_the_example_drawer_lays_out_cleanly() -> None:
    config = CollectionConfig.from_json(json.loads(EXAMPLE.read_text()))
    assert place(config)[1] == []


@pytest.mark.solidcraft
@pytest.mark.skipif(not available(), reason="solidcraft-cli is not on PATH")
def test_collection_assembles_linked_parts(tmp_path) -> None:
    config = {
        "kind": "collection",
        "unit_size": 42,
        "bounds": [126, 84, 60],
        "items": [
            {"name": "plate", "part": {"kind": "baseplate", "grid": {"units_x": 3, "units_y": 2}}},
            {"name": "left", "x": 0, "y": 0, "rotation": 90, "part": {**box(2, 1), "lip": "none"}},
            {"name": "right", "x": 2, "y": 0, "part": {**box(1, 1), "lip": "none"}},
        ],
    }
    path = tmp_path / "set.json"
    path.write_text(json.dumps(config))
    assert main(["collection", "--config", str(path)]) == 0
    folder = tmp_path / "set"
    assert {p.name for p in folder.iterdir()} >= {
        "plate.solidcraft",
        "left.solidcraft",
        "right.solidcraft",
        "set.solidcraft",
    }
    # Inserted parts keep their own coordinates; where they stand is the placement's
    placed = run(
        [
            {"command": "occurrence.properties", "params": {"occurrence": f"{n}:1"}}
            for n in ("left", "right")
        ],
        design=folder / "set.solidcraft",
    ).results[:2]
    left, right = (result["total"]["bbox"] for result in placed)
    # The turned 2x1 bin stands one cell wide and two deep in the first column
    assert left["min"][:2] == pytest.approx((-63 + 0.31, -42 + 0.31), abs=1e-3)
    assert left["max"][:2] == pytest.approx((-21 - 0.31, 42 - 0.31), abs=1e-3)
    assert right["min"][:2] == pytest.approx((21 + 0.31, -42 + 0.31), abs=1e-3)
