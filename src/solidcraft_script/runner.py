"""Run command scripts headless with `solidcraft-cli` and read back what they built."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from solidcraft_script.script import Json

CLI = "solidcraft-cli"
INSPECT = {"command": "document.inspect", "params": {"measure": True}}


class SolidCraftError(RuntimeError):
    pass


@dataclass(frozen=True)
class Body:
    name: str
    volume: float
    area: float
    faces: int
    shells: int
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    center_of_mass: tuple[float, float, float]

    @staticmethod
    def from_inspection(body: Json) -> Body:
        return Body(
            name=body["name"],
            volume=body["volume_mm3"],
            area=body["area_mm2"],
            faces=body["faces"],
            shells=body.get("kernel", {}).get("shells", 1),
            bbox_min=tuple(body["bbox"]["min"]),
            bbox_max=tuple(body["bbox"]["max"]),
            center_of_mass=tuple(body["center_of_mass"]),
        )

    @property
    def size(self) -> tuple[float, float, float]:
        return tuple(b - a for a, b in zip(self.bbox_min, self.bbox_max, strict=True))  # type: ignore[return-value]


@dataclass(frozen=True)
class RunResult:
    results: list[Json]

    @property
    def inspection(self) -> Json:
        return self.results[-1]

    @property
    def bodies(self) -> list[Body]:
        return [Body.from_inspection(b) for b in self.inspection["bodies"] if "volume_mm3" in b]

    def body(self, name: str) -> Body:
        for body in self.bodies:
            if body.name == name:
                return body
        raise KeyError(f"no body {name!r}; bodies: {[b.name for b in self.bodies]}")

    @property
    def problems(self) -> list[str]:
        """Timeline errors and warnings, one line each."""
        return [
            f"{feature['name']}: {feature.get('error') or feature.get('warning')}"
            for feature in self.inspection["timeline"]
            if feature.get("error") or feature.get("warning")
        ]


def available(cli: str = CLI) -> bool:
    return shutil.which(cli) is not None


def run(
    commands: Sequence[Json],
    *,
    design: Path | None = None,
    outputs: Sequence[Path] = (),
    save: Path | None = None,
    cli: str = CLI,
) -> RunResult:
    """Run `commands` (on `design` if given), export each of `outputs` by its extension and save
    the design to `save`. A step or a timeline feature that fails raises SolidCraftError and
    writes nothing."""
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "script.json"
        script.write_text(json.dumps({"commands": [*commands, INSPECT]}))
        args = [cli, "run", str(script), "--results"]
        if design:
            args += ["--in", str(design)]
        for output in outputs:
            args += ["--out", str(output)]
        if save:
            args += ["--save", str(save)]
        done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode:
        raise SolidCraftError(done.stderr.strip().removeprefix("error: "))
    results = json.loads(done.stdout)
    if not isinstance(results, list) or len(results) != len(commands) + 1:
        raise SolidCraftError(f"expected {len(commands) + 1} results, got {len(results)}")
    return RunResult(results)
