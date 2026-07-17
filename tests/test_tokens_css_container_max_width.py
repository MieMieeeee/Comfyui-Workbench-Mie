"""P2-4 regression lock: .gradio-container max-width must allow wide screens.

review P2-4 (2026 July 17): 1400px cap leaves ~260px dead zone on each side on
1920x1080 displays. This is a local desktop tool, not a reading page; horizontal
space should be eaten. Suggested 1600-1800, or max-width:none with min padding.

Test enforces the floor (1600), not the exact pixel; lets the maintainer pick.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

TOKENS_CSS = REPO_ROOT / "app" / "static" / "tokens.css"


def _extract_css_block(text: str, selector: str) -> str | None:
    needle = selector + " {"
    idx = text.find(needle)
    if idx < 0:
        return None
    start = idx + len(needle)
    depth = 1
    i = start
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


def test_gradio_container_max_width_is_wide_enough():
    css = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_css_block(css, ".gradio-container")
    assert body is not None, "tokens.css missing .gradio-container block"

    m = re.search(r"max-width:\s*(\d+)px", body)
    assert m, "no max-width declared on .gradio-container"

    width = int(m.group(1))
    assert width >= 1600, (
        f".gradio-container max-width={width}px too narrow for desktop workbench; "
        f"wide screens have big dead zones. review P2-4: bump to 1600-1800."
    )
