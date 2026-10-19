"""Draw the doc's figures from the generator's own geometry and write them into the page.

uv run python docs/figures.py            rewrite the figures in gridfinity.html
uv run python docs/figures.py --check    fail if the page holds a stale figure
"""

from __future__ import annotations

import sys
from pathlib import Path

from gridfinity.box import BinShape
from gridfinity.config import BoxConfig, Grid
from gridfinity.standard import DEFAULT

PAGE = Path(__file__).parent / "gridfinity.html"
START = "<!-- figure:bin-section -->"
END = "<!-- /figure:bin-section -->"

# Millimetres to figure units, and how far into the bin the section reaches
SCALE = 17.0
REACH = 9.0
LEFT, TOP = 150.0, 24.0
# Wide enough that, drawn across a doc's column, the figure is shown about full size
WIDTH = 1000


def bin_section() -> str:
    """Half a bin's wall, from its outer face inward: the foot, the floor, the wall and lip."""
    shape = BinShape.of(BoxConfig(grid=Grid(1, 1), units_z=3))
    height = shape.height
    foot = [(inset, DEFAULT.foot_height - depth) for inset, depth in DEFAULT.foot]
    outline = [
        (foot[-1][0], 0.0),
        (REACH, 0.0),
        (REACH, shape.floor),
        *reversed(shape.inner),
        *foot,
    ]

    def x(u: float) -> float:
        return LEFT + u * SCALE

    def y(z: float) -> float:
        return TOP + (height - z) * SCALE

    width = WIDTH
    tall = y(0) + 34
    path = (
        " ".join(
            f"{'M' if i == 0 else 'L'}{x(u):.1f},{y(z):.1f}" for i, (u, z) in enumerate(outline)
        )
        + " Z"
    )
    nominal = shape.nominal
    levels = [
        (0.0, "0 · underside of the foot"),
        (DEFAULT.foot_height, f"{DEFAULT.foot_height:g} · top of the foot"),
        (shape.floor, f"{shape.floor:g} · floor"),
        (nominal, "7 × height units · walls, ledges and scoops end"),
        (height, f"7 × units + {height - nominal:.2f} · top of the lip"),
    ]
    marks = []
    for z, words in levels:
        marks.append(
            f'<line x1="{x(0) - 8:.1f}" y1="{y(z):.1f}" x2="{x(REACH) + 8:.1f}" y2="{y(z):.1f}" '
            'style="stroke: var(--rule-strong)" stroke-width="1" stroke-dasharray="3 4"/>'
        )
        marks.append(text(x(REACH) + 14, y(z) + 4, words))
    deepest = max(i for i, _ in shape.inner)
    marks.append(text(x(DEFAULT.foot_inset) + 6, y(0.0) + 18, f"{DEFAULT.foot_inset:g}"))
    marks.append(text(x(shape.wall) + 6, y(shape.floor + 2.0), f"{shape.wall:g} wall"))
    marks.append(text(x(deepest) + 6, y(shape.inner[-3][1]) + 18, f"{deepest:g}"))
    label = (
        "Section through a bin's wall from its outer face inward: the stepped foot below the "
        "floor, the outer wall, and the stacking lip whose 45 degree slopes take the foot of "
        "the bin stacked on it."
    )
    body = (
        text(x(0) - 10, y(height / 2), "outer face", anchor="end")
        + f'<path d="{path}" style="fill: var(--accent-soft); stroke: var(--accent)" '
        'stroke-width="1.6" stroke-linejoin="round"/>'
        + "".join(marks)
        + text(8, tall - 8, "fig-bin-section", size=10, ink="--ink-3")
    )
    frame = f'class="fig" viewBox="0 0 {width:.0f} {tall:.0f}" role="img" aria-label="{label}"'
    return f"<svg {frame}>{body}</svg>"


def text(
    x: float, y: float, words: str, size: int = 13, ink: str = "--ink-2", anchor: str = ""
) -> str:
    align = f' text-anchor="{anchor}"' if anchor else ""
    style = f'style="fill: var({ink})" font-size="{size}"'
    return f'<text x="{x:.1f}" y="{y:.1f}"{align} {style}>{words}</text>'


def render(page: str) -> str:
    before, rest = page.split(START, 1)
    _, after = rest.split(END, 1)
    return f"{before}{START}\n        {bin_section()}\n        {END}{after}"


def main() -> int:
    page = PAGE.read_text()
    updated = render(page)
    if "--check" in sys.argv:
        if updated != page:
            print("gridfinity.html holds a stale figure: run docs/figures.py")
            return 1
        return 0
    PAGE.write_text(updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
