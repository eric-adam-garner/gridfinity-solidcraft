"""Command line: build a part headless and write files, or build it in the running app."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from gridfinity.baseplate import build_baseplate
from gridfinity.box import build_box
from gridfinity.clip import build_clip
from gridfinity.config import (
    BaseplateConfig,
    BoxConfig,
    ClipConfig,
    ConfigError,
    Element,
    ElementKind,
    HoleStyle,
    LipStyle,
    Orientation,
    PartConfig,
    PartKind,
    read,
    write,
)
from solidcraft_script.control import DEFAULT_PORT, ControlClient
from solidcraft_script.runner import Body, SolidCraftError, run
from solidcraft_script.script import Script

EXPORTS = (".stl", ".step", ".stp", ".3mf", ".obj")
DESIGNS = (".solidcraft", ".json")


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        kind, config = configure(args)
        if args.print_config:
            print(write(config, kind), end="")
            return 0
        script = build(kind, config)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.script:
        script.save(args.script)
    outputs = args.out or (
        [] if args.live or args.script else [Path(f"{default_name(kind, config)}.stl")]
    )
    try:
        if args.live:
            build_live(script, args.port, default_name(kind, config), outputs)
        elif outputs:
            build_headless(script, outputs)
    except (SolidCraftError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="gridfinity", description=__doc__)
    parts = top.add_subparsers(dest="kind", required=True)

    box = parts.add_parser("box", help="a bin")
    _common(box)
    _grid(box)
    box.add_argument("--height", type=int, help="height in 7 mm units (2-20)")
    box.add_argument("--lip", choices=[s.value for s in LipStyle])
    _holes(box, corner=True)
    box.add_argument("--outer-wall", type=float, help="outer wall thickness, mm")
    box.add_argument("--inner-wall", type=float, help="thickness of inner walls, mm")
    box.add_argument("--scoop-shape", type=float, help="scoop curve, 0.1 (shallow) to 0.4 (round)")
    for kind in ElementKind:
        box.add_argument(
            f"--{kind.value}",
            action="append",
            default=[],
            metavar="X,Y,LENGTH[,x|y][,flip]",
            help=f"add a {kind.value}; positions and length in twelfths of a grid unit",
        )

    plate = parts.add_parser("baseplate", help="a baseplate")
    _common(plate)
    _grid(plate)
    _holes(plate, corner=False)
    plate.add_argument(
        "--connectable", action="store_true", default=None, help="connector slots on the edges"
    )
    plate.add_argument(
        "--size", type=float, nargs=2, metavar=("X", "Y"), help="trim to this size, mm"
    )

    clip = parts.add_parser("clip", help="a clip joining two connectable baseplates")
    _common(clip)
    clip.add_argument("--unit-size", type=float, help="grid unit size, mm")
    clip.add_argument("--tolerance", type=float, help="extra play, mm (-0.05 to 0.2)")
    return top


def _common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--config", type=Path, help="JSON file of settings; options given here override it"
    )
    sub.add_argument(
        "--out",
        type=Path,
        action="append",
        help="write .stl .step .3mf .obj .solidcraft (repeatable)",
    )
    sub.add_argument("--script", type=Path, help="also write the SolidCraft command script (JSON)")
    sub.add_argument(
        "--live", action="store_true", help="build in the running SolidCraft app, in a new design"
    )
    sub.add_argument("--port", type=int, default=DEFAULT_PORT, help="the app's control port")
    sub.add_argument("--print-config", action="store_true", help="print the settings as JSON")


def _grid(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--units", type=int, nargs=2, metavar=("X", "Y"), help="grid units (1-20 each)"
    )
    sub.add_argument("--unit-size", type=float, help="grid unit size, mm (12-70)")


def _holes(sub: argparse.ArgumentParser, corner: bool) -> None:
    styles = [s.value for s in HoleStyle if corner or s != HoleStyle.CORNER]
    sub.add_argument("--magnets", choices=styles)
    sub.add_argument("--screws", choices=styles)
    sub.add_argument("--magnet-diameter", type=float, help="mm (2-8.2)")
    sub.add_argument("--magnet-height", type=float, help="mm (1-4)")


def configure(args: argparse.Namespace) -> tuple[PartKind, PartConfig]:
    kind = PartKind.CLIP if args.kind == "clip" else PartKind(args.kind)
    defaults = {
        PartKind.BOX: BoxConfig,
        PartKind.BASEPLATE: BaseplateConfig,
        PartKind.CLIP: ClipConfig,
    }
    config = read(args.config, kind) if args.config else defaults[kind]()
    if kind == PartKind.CLIP:
        changes = _given(unit_size=args.unit_size, tolerance=args.tolerance)
        return kind, replace(config, **changes)

    grid = config.grid
    if args.units:
        grid = replace(grid, units_x=args.units[0], units_y=args.units[1])
    if args.unit_size is not None:
        grid = replace(grid, unit_size=args.unit_size)
    holes = replace(
        config.holes,
        **_given(
            magnets=args.magnets and HoleStyle(args.magnets),
            screws=args.screws and HoleStyle(args.screws),
            magnet_diameter=args.magnet_diameter,
            magnet_height=args.magnet_height,
        ),
    )
    if kind == PartKind.BASEPLATE:
        changes = _given(connectable=args.connectable)
        if args.size:
            changes.update(size_x=args.size[0], size_y=args.size[1])
        return kind, replace(config, grid=grid, holes=holes, **changes)

    elements = list(config.elements)
    for element_kind in ElementKind:
        elements += [
            parse_element(element_kind, text) for text in getattr(args, element_kind.value)
        ]
    changes = _given(
        units_z=args.height,
        lip=args.lip and LipStyle(args.lip),
        outer_wall=args.outer_wall,
        inner_wall=args.inner_wall,
        scoop_shape=args.scoop_shape,
    )
    return kind, replace(config, grid=grid, holes=holes, elements=tuple(elements), **changes)


def _given(**values: object) -> dict[str, object]:
    return {name: value for name, value in values.items() if value is not None}


def parse_element(kind: ElementKind, text: str) -> Element:
    """`X,Y,LENGTH` with an optional orientation `x` or `y` and an optional `flip`."""
    parts = [p.strip().lower() for p in text.split(",") if p.strip()]
    try:
        x, y, length = (int(p) for p in parts[:3])
    except ValueError as error:
        raise ConfigError(f"{kind.value} {text!r}: expected X,Y,LENGTH") from error
    rest = set(parts[3:])
    unknown = rest - {"x", "y", "flip"}
    if unknown or {"x", "y"} <= rest:
        raise ConfigError(f"{kind.value} {text!r}: unexpected {sorted(unknown) or 'x and y'}")
    orientation = Orientation.Y if "y" in rest else Orientation.X
    return Element(kind, x, y, length, orientation, flip="flip" in rest)


def build(kind: PartKind, config: PartConfig) -> Script:
    if isinstance(config, BoxConfig):
        return build_box(config)
    if isinstance(config, BaseplateConfig):
        return build_baseplate(config)
    return build_clip(config)


def default_name(kind: PartKind, config: PartConfig) -> str:
    """File names as the web generator gives them."""
    if isinstance(config, BoxConfig):
        g = config.grid
        return f"box-{g.units_x}-{g.units_y}-{config.units_z}"
    if isinstance(config, BaseplateConfig):
        g = config.grid
        trimmed = "-cut" if config.size_x is not None or config.size_y is not None else ""
        return f"baseplate-{g.units_x}-{g.units_y}{trimmed}"
    return f"connection-clip-{config.unit_size:g}"


def build_headless(script: Script, outputs: Sequence[Path]) -> None:
    exports = [p for p in outputs if p.suffix.lower() in EXPORTS]
    designs = [p for p in outputs if p.suffix.lower() in DESIGNS]
    unknown = [p for p in outputs if p not in exports and p not in designs]
    if unknown:
        raise SolidCraftError(
            f"cannot write {', '.join(map(str, unknown))}: use {', '.join(EXPORTS + DESIGNS)}"
        )
    started = time.monotonic()
    result = run(script.commands, outputs=exports, save=designs[0] if designs else None)
    for extra in designs[1:]:
        run(script.commands, save=extra)
    _report(result.bodies, result.problems, time.monotonic() - started, outputs)


def build_live(script: Script, port: int, name: str, outputs: Sequence[Path]) -> None:
    started = time.monotonic()
    with ControlClient(port) as app:
        app.execute("file.new", {"name": name})
        app.batch(script.commands)
        for path in outputs:
            path = path.resolve()
            if path.suffix.lower() in DESIGNS:
                app.execute("file.save", {"path": str(path)})
            else:
                app.execute("file.export", {"path": str(path)})
        inspection = app.inspect()
    bodies = [(b["name"], b["volume_mm3"]) for b in inspection["bodies"] if "volume_mm3" in b]
    problems = [
        f"{f['name']}: {f.get('error') or f.get('warning')}"
        for f in inspection["timeline"]
        if f.get("error") or f.get("warning")
    ]
    print(
        f"built in the app in {time.monotonic() - started:.1f} s: "
        + ", ".join(f"{n} {v:.1f} mm3" for n, v in bodies)
    )
    for problem in problems:
        print(f"warning: {problem}")
    for path in outputs:
        print(f"wrote {path}")


def _report(
    bodies: Sequence[Body], problems: Sequence[str], seconds: float, outputs: Sequence[Path]
) -> None:
    summary = ", ".join(f"{b.name} {b.volume:.1f} mm3" for b in bodies)
    print(f"built in {seconds:.1f} s: {summary}")
    for problem in problems:
        print(f"warning: {problem}")
    for path in outputs:
        print(f"wrote {path}")
