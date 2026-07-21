"""After history tab removal: build_ui must not register the history tab.

Lock for the 2026-07-18 redesign decision: history tab is too slow / too niche,
replaced with a simple "open ComfyUI output folder" button in the workflow sidebar.

Contract:
  - No gr.Tab labeled 历史记录 in the built demo.
  - All history-only symbols are gone from scail2_app (no stale references).
  - build_ui still returns a usable demo with the workflow tab + settings tab.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import gradio as gr

from app import scail2_app


HIST_LABEL = chr(0x5386) + chr(0x53f2) + chr(0x8bb0) + chr(0x5f55)  # 历史记录


def test_no_history_tab_in_built_demo():
    """build_ui must not register a tab labeled 历史记录 after the redesign.

    The tab was removed because the user (2026-07-18) questioned its necessity,
    and the per-row Dataframe + 6-detail-output render was a real perf bottleneck."""
    demo = scail2_app.build_ui()
    # Gradio 6: top-level gr.Tabs container holds gr.Tab items as children
    tab_labels = _top_level_tab_labels(demo)
    assert HIST_LABEL not in tab_labels, (
        f"history tab (label={HIST_LABEL!r}) still present in demo after redesign; "
        f"all tabs: {tab_labels}"
    )


def _top_level_tab_labels(demo):
    """Walk top-level gr.Tabs containers and return all gr.Tab item labels."""
    labels = []
    for child in (demo.children or []):
        if isinstance(child, gr.Tabs):
            for sub in (child.children or []):
                if isinstance(sub, gr.Tab):
                    labels.append(getattr(sub, "label", "") or "")
    return labels


def test_no_history_only_symbols_in_scail2_app():
    """No history-only symbols should remain in scail2_app after removal."""
    removed = [
        "_build_history_tab",
        "_refresh_history_dataframe",
        "_refresh_history_details",
        "_refresh_history_filtered",
        "_on_history_row_select",
        "_HISTORY_RUNS_CACHE",
        "_make_detail_from_run",
        "_stage_rerun",
        "_fill_from_manifest",
    ]
    src_path = Path(scail2_app.__file__)
    src = src_path.read_text(encoding="utf-8")
    leftovers = [s for s in removed if s in src]
    assert not leftovers, (
        f"history-only symbols still in scail2_app after redesign; "
        f"leftovers: {leftovers}"
    )


def test_workflow_and_settings_tabs_still_present():
    """Workflow tab and settings tab must still exist after removing history.

    The workflow tab is labeled "运行" (run), since the historical name was
    workflow/工作流; confirm either is still present."""
    demo = scail2_app.build_ui()
    labels = set(_top_level_tab_labels(demo))
    assert labels, "no tabs in built demo -- build_ui is broken"
    RUN_LABEL = chr(0x8fd0) + chr(0x884c)
    SET_LABEL = chr(0x7cfb) + chr(0x7edf) + chr(0x8bbe) + chr(0x7f6e)
    assert RUN_LABEL in labels, f"运行 tab missing; tabs: {labels}"
    assert SET_LABEL in labels, f"系统设置 tab missing; tabs: {labels}"

