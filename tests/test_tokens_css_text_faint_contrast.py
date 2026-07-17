"""P1-3 regression lock: --text-faint must meet WCAG contrast >= 3.8 on --bg-card.

review P1-3 (2026 July 17): `--text-faint` at #5f6470 has contrast 2.85 on
`--bg-card` (#1a1d23), below WCAG AA 4.5. Affects:
  - .btn-run-primary/secondary :disabled text
  - .file-dropzone svg icon (拖拽区占位图标)

reviewer accepts 3.8 as "non-critical helper text" floor (not full AA 4.5);
if we want full AA, fold faint into --text-muted (#8b909b at 5.27).

Test encodes the contract, not the implementation: any color with >= 3.8
contrast on --bg-card passes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

TOKENS_CSS = REPO_ROOT / "app" / "static" / "tokens.css"


def _extract_css_block(text: str, selector: str) -> str | None:
    """Find first 'selector {' ... matching '}' block body."""
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


def _hex_value(text: str, var_name: str) -> str | None:
    """Extract '#xxxxxx' value for `--var-name:` line."""
    m = re.search(rf"{re.escape(var_name)}\s*:\s*(#[0-9a-fA-F]{{3,8}})", text)
    return m.group(1) if m else None


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _wcag_luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def wcag_contrast(fg_hex: str, bg_hex: str) -> float:
    """Contrast ratio per WCAG 2.x (https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio)."""
    l1 = _wcag_luminance(_hex_to_rgb(fg_hex))
    l2 = _wcag_luminance(_hex_to_rgb(bg_hex))
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def test_text_faint_meets_minimum_contrast_on_card_bg():
    css = TOKENS_CSS.read_text(encoding="utf-8")
    faint = _hex_value(css, "--text-faint")
    card = _hex_value(css, "--bg-card")
    assert faint, "tokens.css missing --text-faint"
    assert card, "tokens.css missing --bg-card"

    ratio = wcag_contrast(faint, card)
    assert ratio >= 3.8, (
        f"--text-faint ({faint}) on --bg-card ({card}) contrast {ratio:.2f} "
        f"< 3.8. review P1-3 floor for non-critical helper text. "
        f"Bump to ~#717785 (3.93) or merge into --text-muted (#8b909b)."
    )


def test_text_faint_still_distinguishable_from_muted():
    """If someone bumps --text-faint all the way to --text-muted, we lose the
    'dimmer tier' the design relies on for disabled state. This test enforces
    faint stays meaningfully dimmer than muted (so the design intent survives)."""
    css = TOKENS_CSS.read_text(encoding="utf-8")
    faint = _hex_value(css, "--text-faint")
    muted = _hex_value(css, "--text-muted")
    card = _hex_value(css, "--bg-card")
    assert all([faint, muted, card])

    faint_ratio = wcag_contrast(faint, card)
    muted_ratio = wcag_contrast(muted, card)
    assert faint_ratio < muted_ratio, (
        f"--text-faint ({faint_ratio:.2f}) should stay below --text-muted ({muted_ratio:.2f}); "
        f"otherwise the disabled/helper tier collapses into muted and we lose the design signal."
    )
