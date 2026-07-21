"""P2-5 regression lock: build_ui() must include an h1 app title above main Tabs.

review P2-5 (2026 July 17): page has no h1 / h2 (probe result HEADERS: []).
Only titles are the per-preset h3. Browser tab title says "ComfyUI Web Workflow"
but the page itself has no visible app brand, hurting 'this is an application' feel.

Contract: build_ui() registers at least one gr.Markdown whose value starts with
'# ' (h1 syntax). Test inspects the rendered Blocks tree, not source text, so it
survives refactors (e.g. extracting _render_header() helper).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import gradio as gr

from app import scail2_app


def _find_h1_markdown(demo):
    """Return the first gr.Markdown component whose value starts with '# '."""
    for comp in demo.blocks.values():
        if not isinstance(comp, gr.components.Markdown):
            continue
        val = getattr(comp, "value", None)
        if isinstance(val, str) and val.lstrip().startswith("# "):
            return comp
    return None


def test_build_ui_registers_h1_app_title():
    demo = scail2_app.build_ui()
    h1 = _find_h1_markdown(demo)
    assert h1 is not None, (
        "build_ui() did not register an h1 (Markdown value starting with '# '). "
        "review P2-5: add e.g. `gr.Markdown('# 🎬 ComfyUI 工作流运行器')` "
        "above the main Tabs in build_ui()."
    )


def test_build_ui_h1_is_visible():
    """The h1 should actually render -- not be hidden."""
    demo = scail2_app.build_ui()
    h1 = _find_h1_markdown(demo)
    assert h1 is not None
    assert getattr(h1, "visible", True), "h1 Markdown is hidden (visible=False)"
