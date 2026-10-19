"""The doc carries the repo's stylesheet and a figure drawn from the current geometry."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).parent.parent / "docs"


def test_doc_embeds_the_canonical_stylesheet() -> None:
    page = (DOCS / "gridfinity.html").read_text()
    css = page[page.index("<style>\n") + len("<style>\n") : page.index("</style>")]
    assert css == (DOCS / "style.css").read_text()


def test_doc_figure_is_current() -> None:
    done = subprocess.run(
        [sys.executable, str(DOCS / "figures.py"), "--check"], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout
