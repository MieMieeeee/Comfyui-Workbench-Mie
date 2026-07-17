"""P2-6 regression lock: .custom-radio label padding must be compact.

review P2-6 (2026 July 17): after P0-2 removed the English category suffix, each
Radio row should naturally collapse to single-line ~40px. Default padding
`var(--space-3) var(--space-4)` (12px / 16px) keeps it too tall. Drop vertical
to `var(--space-2)` (8px) for the workbench-density look.

Test encodes the contract: vertical padding of `.custom-radio label` must be
`var(--space-2)` or tighter. Implementation can swap exact spacing tokens as
long as it stays compact.
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


def test_custom_radio_label_padding_uses_space_2_vertical():
    css = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_css_block(css, ".custom-radio label")
    assert body is not None, "tokens.css missing .custom-radio label block"

    m = re.search(r"padding:\s*([^;]+);", body)
    assert m, ".custom-radio label has no padding declaration"
    padding = m.group(1).strip()

    # expect shorthand like "var(--space-2) var(--space-3)" or "var(--space-2) var(--space-X)"
    first = padding.split()[0]  # vertical (top/bottom) in shorthand
    assert first == "var(--space-2)", (
        f".custom-radio label vertical padding = {first!r}; "
        f"review P2-6 wants compact `var(--space-2)` (8px) so each row drops to ~40px. "
        f"Current full padding shorthand: {padding!r}"
    )
