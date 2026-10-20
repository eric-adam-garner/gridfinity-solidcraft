"""An MCP server that builds Gridfinity parts: a bin, baseplate, clip or collection per tool
call, in a new tab of the running SolidCraft app or as files."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from gridfinity import collection
from gridfinity.cli import build, build_headless, build_live, collect, configure, default_name
from gridfinity.config import (
    CLIP_TOLERANCE,
    MAGNET_DIAMETER,
    MAGNET_HEIGHT,
    SCOOP_SHAPE,
    UNIT_SIZE,
    UNITS_XY,
    UNITS_Z,
    WALL_THICKNESS,
    ConfigError,
    ElementKind,
    HoleStyle,
    LipStyle,
    Orientation,
    PartKind,
    write,
)
from solidcraft_script.control import DEFAULT_PORT, ControlError
from solidcraft_script.mcp_server import Json, Tool, ToolError, serve
from solidcraft_script.runner import SolidCraftError

NAME = "gridfinity"
INSTRUCTIONS = (
    "Builds Gridfinity storage parts as SolidCraft designs: bins with walls, label ledges and "
    "scoops; baseplates; the clips that join connectable baseplates; and collections of parts "
    "laid out in a drawer. Use these tools for any Gridfinity part rather than modelling it "
    "by hand. By default a part is built in a new tab of the open SolidCraft window, where the "
    "SolidCraft tools can go on to change it; `outputs` also writes files. Every reply ends "
    "with the part's settings as JSON, which a later call can pass back via `config` once "
    "saved to a file."
)
LIVE = {
    "type": "boolean",
    "description": "Build in a new tab of the open SolidCraft window (default true); false "
    "builds headless and only writes `outputs`, or an STL named after the part.",
}
OUTPUTS = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Files to write: .stl, .step, .3mf, .obj export the part, .solidcraft or "
    ".json save the design. Relative paths are in the session's folder.",
}
CONFIG = {
    "type": "string",
    "description": "A JSON settings file to start from; the other arguments override it.",
}
ELEMENT = {
    "type": "object",
    "properties": {
        "kind": {"enum": [kind.value for kind in ElementKind]},
        "x": {"type": "integer", "minimum": 0},
        "y": {"type": "integer", "minimum": 0},
        "length": {"type": "integer", "minimum": 1},
        "orientation": {"enum": [o.value for o in Orientation], "description": "Default x."},
        "flip": {"type": "boolean", "description": "Face -Y (or -X) instead; default false."},
    },
    "required": ["kind", "x", "y", "length"],
    "additionalProperties": False,
}
ELEMENTS_HELP = (
    "Walls, label ledges and scoops along lines of the grid divided into twelfths of a unit. "
    "x and y count twelfths from the bin's -X/-Y corner, length counts twelfths along the "
    "line. An x element runs along X on the line y; a y element along Y on the line x. A "
    "ledge (a 15 mm shelf at the top) or a scoop (a curve up from the floor) faces +Y for an x "
    "element and +X for a y element, the other way when flipped. For a 3 x 2 bin, a "
    'full-depth divider one unit in is {"kind": "wall", "x": 12, "y": 0, "length": 24, '
    '"orientation": "y"}, and a label shelf along the back is {"kind": "ledge", "x": 0, '
    '"y": 24, "length": 36, "flip": true}.'
)
COLLECTION_HELP = (
    "The layout: {unit_size, bounds: [width, depth, height] in mm, items: [{name, x, y, z, "
    "rotation, part}]}. x and y are grid cells from the bounds' -X/-Y corner, z is height "
    "units, rotation 0, 90, 180 or 270; part holds a part's settings with its kind, e.g. "
    '{"kind": "box", "grid": {"units_x": 2, "units_y": 1}, "units_z": 3}. Bins standing on a '
    "baseplate go at z 0, as the baseplate does."
)
DESCRIPTIONS = {
    PartKind.BOX: "Build a Gridfinity bin: feet on a grid, a floor, an outer wall with a "
    "stacking lip, optional magnet and screw holes, and walls, label ledges and scoops inside.",
    PartKind.BASEPLATE: "Build a Gridfinity baseplate: an open-bottomed pocket for every grid "
    "cell, optional magnet and screw pads, connector slots, trimming to a drawer's size.",
    PartKind.CLIP: "Build the clip that joins two connectable Gridfinity baseplates.",
}
COLLECTION_DESCRIPTION = (
    "Lay several Gridfinity parts out on one grid in a drawer-sized volume: each part is built "
    "and saved as its own design, and a collection design links them in place. Warns about "
    "parts that overlap or stick out of the bounds."
)


def tools(port: int) -> list[Tool]:
    def part(kind: PartKind, schema: Json) -> Tool:
        def run(arguments: Json) -> str:
            return build_part(kind, arguments, schema, port)

        return Tool(kind.value, DESCRIPTIONS[kind], schema, run)

    def group(arguments: Json) -> str:
        return build_collection(arguments, port)

    return [
        part(PartKind.BOX, box_schema()),
        part(PartKind.BASEPLATE, baseplate_schema()),
        part(PartKind.CLIP, clip_schema()),
        Tool("collection", COLLECTION_DESCRIPTION, collection_schema(), group),
    ]


def box_schema() -> Json:
    return _schema(
        {
            **_grid(),
            "height": {
                "type": "integer",
                "minimum": UNITS_Z[0],
                "maximum": UNITS_Z[1],
                "description": "Height in units of 7 mm; default 3.",
            },
            "lip": {
                "enum": [s.value for s in LipStyle],
                "description": "Stacking lip; default is default.",
            },
            **_holes(list(HoleStyle)),
            "outer_wall": _number(WALL_THICKNESS, "Outer wall thickness in mm; default 1.2."),
            "inner_wall": _number(WALL_THICKNESS, "Inside walls' thickness, mm; default 0.8."),
            "scoop_shape": _number(SCOOP_SHAPE, "Scoop curve, 0.1 shallow to 0.4 round."),
            "size": _pair(
                "number",
                "Trim the bin to this width and depth in mm, keeping its -X/-Y corner; each "
                "within the last grid unit.",
            ),
            "split_top": {
                "type": "boolean",
                "description": "Build the top 1 mm of the bin as a second body, BinTop.",
            },
            "elements": {"type": "array", "items": ELEMENT, "description": ELEMENTS_HELP},
            "config": CONFIG,
            "live": LIVE,
            "outputs": OUTPUTS,
        }
    )


def baseplate_schema() -> Json:
    return _schema(
        {
            **_grid(),
            **_holes([HoleStyle.NONE, HoleStyle.FULL]),
            "connectable": {
                "type": "boolean",
                "description": "Connector slots on the outer edges, for clips; default false.",
            },
            "size": _pair(
                "number",
                "Trim the plate to this width and depth in mm, keeping its -X/-Y corner, e.g. "
                "to fit a drawer; each within the last grid unit.",
            ),
            "config": CONFIG,
            "live": LIVE,
            "outputs": OUTPUTS,
        }
    )


def clip_schema() -> Json:
    return _schema(
        {
            "unit_size": _number(UNIT_SIZE, "Grid pitch in mm of the plates it joins."),
            "tolerance": _number(CLIP_TOLERANCE, "Extra play in mm; default 0."),
            "config": CONFIG,
            "live": LIVE,
            "outputs": OUTPUTS,
        }
    )


def collection_schema() -> Json:
    return _schema(
        {
            "collection": {"type": "object", "description": COLLECTION_HELP},
            "config": {"type": "string", "description": "A collection JSON file, instead."},
            "name": {"type": "string", "description": "The collection design's name."},
            "folder": {
                "type": "string",
                "description": "Where each part's design goes; default a folder named after "
                "the collection in the session's folder.",
            },
            "exports": {
                "type": "array",
                "items": {"enum": ["stl", "step", "3mf"]},
                "description": "Also export every part in these formats.",
            },
            "live": {
                "type": "boolean",
                "description": "Assemble the collection in a new tab of the open window "
                "(default true); false saves it headless.",
            },
        }
    )


def build_part(kind: PartKind, arguments: Json, schema: Json, port: int) -> str:
    _check(arguments, schema)
    options = {k: v for k, v in arguments.items() if k not in ("live", "outputs")}
    try:
        config = configure(kind, options)
        script = build(kind, config)
        name = default_name(kind, config)
        outputs = [Path(path) for path in arguments.get("outputs", [])]
        if arguments.get("live", True):
            lines = build_live(script, port, name, outputs)
        else:
            lines = build_headless(script, outputs or [Path(f"{name}.stl")])
    except (ConfigError, SolidCraftError, ControlError, OSError) as error:
        raise ToolError(str(error)) from error
    return "\n".join([*lines, "settings:", write(config, kind).rstrip()])


def build_collection(arguments: Json, port: int) -> str:
    _check(arguments, collection_schema())
    try:
        if "collection" in arguments:
            layout = collection.CollectionConfig.from_json(arguments["collection"])
            name = arguments.get("name", "collection")
        elif "config" in arguments:
            path = Path(arguments["config"])
            layout = collection.read(path)
            name = arguments.get("name", path.stem)
        else:
            raise ToolError("give the layout as `collection`, or a file of it as `config`")
        folder = Path(arguments.get("folder", name))
        out = folder / f"{name}.solidcraft"
        live = arguments.get("live", True)
        lines = collect(layout, name, folder, arguments.get("exports", []), out, live, port)
    except (ConfigError, SolidCraftError, ControlError, OSError, KeyError) as error:
        raise ToolError(str(error)) from error
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gridfinity-mcp", description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SOLIDCRAFT_PORT", DEFAULT_PORT)),
        help="the SolidCraft app's control port",
    )
    args = parser.parse_args(argv)
    serve(NAME, _version(), tools(args.port), INSTRUCTIONS)


def _schema(properties: Json) -> Json:
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _number(bounds: tuple[float, float], description: str) -> Json:
    return {
        "type": "number",
        "minimum": bounds[0],
        "maximum": bounds[1],
        "description": description,
    }


def _pair(kind: str, description: str, bounds: tuple[float, float] | None = None) -> Json:
    item: Json = {"type": kind}
    if bounds:
        item |= {"minimum": bounds[0], "maximum": bounds[1]}
    return {
        "type": "array",
        "items": item,
        "minItems": 2,
        "maxItems": 2,
        "description": description,
    }


def _grid() -> Json:
    return {
        "units": _pair("integer", "Grid units across (X) and deep (Y); default 2 x 2.", UNITS_XY),
        "unit_size": _number(UNIT_SIZE, "Grid pitch in mm; default 42."),
    }


def _holes(styles: Sequence[HoleStyle]) -> Json:
    names = [style.value for style in styles]
    return {
        "magnets": {"enum": names, "description": "Magnet pockets under the part; default none."},
        "screws": {"enum": names, "description": "Screw holes under the part; default none."},
        "magnet_diameter": _number(MAGNET_DIAMETER, "Magnet diameter in mm; default 6.2."),
        "magnet_height": _number(MAGNET_HEIGHT, "Magnet height in mm; default 2.1."),
    }


def _check(arguments: Json, schema: Json) -> None:
    unknown = sorted(set(arguments) - set(schema["properties"]))
    if unknown:
        raise ToolError(f"unknown arguments {unknown}; it takes {sorted(schema['properties'])}")


def _version() -> str:
    try:
        return version("gridfinity-solidcraft")
    except PackageNotFoundError:
        return "0"
