"""P0-1 regression lock: history tab must load data on demo startup.

review P0-1 (2026 July 17): first open of the history tab shows "0 records" because
nothing wires demo.load to `_refresh_history_filtered`. Disk actually has 10+
manifests in app/data/runs/. Test encodes the contract: at least one
BlockFunction registered as `demo.load` (Gradio 6 marker: targets == [(0, 'load')])
must call `scail2_app._refresh_history_filtered`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import scail2_app


def _load_block_functions(demo):
    """Return BlockFunctions whose target tuple ends with 'load' (Gradio 6 marker)."""
    out = []
    for bf in demo.fns.values():
        if not bf.targets:
            continue
        # targets is a list of (component_id, trigger_name) tuples
        if any(t[1] == "load" for t in bf.targets):
            out.append(bf)
    return out


def test_history_load_registered_on_demo_startup():
    """build_ui() must register a demo.load that fires _refresh_history_filtered."""
    demo = scail2_app.build_ui()
    load_bfs = _load_block_functions(demo)

    refresh = scail2_app._refresh_history_filtered
    matches = [bf for bf in load_bfs if bf.fn is refresh]

    assert matches, (
        "demo.load did not register _refresh_history_filtered -> "
        "first open of history tab shows empty table even though "
        "app/data/runs/ has manifests. Review P0-1 fix: call "
        "demo.load(fn=_refresh_history_filtered, ...) inside _build_history_tab."
    )


def test_history_load_uses_event_inputs_outputs():
    """The load wiring must reuse the same inputs/outputs as the existing click/change hooks,
    so first-paint and refresh-on-filter produce identical layouts."""
    demo = scail2_app.build_ui()
    load_bfs = _load_block_functions(demo)

    refresh = scail2_app._refresh_history_filtered
    matches = [bf for bf in load_bfs if bf.fn is refresh]

    assert matches, "no demo.load -> _refresh_history_filtered wiring"
    # inputs should be exactly 2 (preset_filter + status_filter)
    bf = matches[0]
    assert bf.inputs is not None and len(bf.inputs) == 2, (
        f"expected 2 inputs (preset_filter + status_filter), got {bf.inputs!r}"
    )
    # outputs should be 6 (df + summary + media + manifest + prompt_md + count_label)
    assert bf.outputs is not None and len(bf.outputs) == 6, (
        f"expected 6 outputs, got {bf.outputs!r}"
    )
