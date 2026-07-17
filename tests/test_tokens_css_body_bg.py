"""P3-7 regression lock: body background must be var(--bg-app).

review P3-7 (2026 July 17): Gradio 6 inline `<style>` in <head> writes
`body { background: var(--bg-dark); }` and our `:root.dark { --body-background-fill: var(--bg-app) }`
loses the priority fight. Result: edge of `.gradio-container` shows a subtle
color halo (body=#0a0f1e, app=#0f1115).

Fix: add an explicit `body { background: var(--bg-app) !important; }` rule.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

TOKENS_CSS = REPO_ROOT / "app" / "static" / "tokens.css"


def test_body_background_uses_bg_app():
    css = TOKENS_CSS.read_text(encoding="utf-8")
    # match body { ... background: var(--bg-app) ... !important; ... }
    pat = re.compile(
        r"body\s*\{[^}]*background\s*:\s*var\(--bg-app\)\s*!important",
        re.DOTALL,
    )
    assert pat.search(css), (
        "tokens.css missing `body { background: var(--bg-app) !important; }` "
        "rule. review P3-7: Gradio 6 inline style overrides our :root.dark "
        "settings, leaving a subtle color halo at the container edge."
    )
