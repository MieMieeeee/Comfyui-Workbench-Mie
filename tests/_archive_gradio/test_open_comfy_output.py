"""Test the new "open ComfyUI output folder" button added 2026-07-18.

Replaces the history tab. The button opens the ComfyUI output directory
(config.COMFY_OUTPUT_DIR) in the OS file explorer via os.startfile().

Contract:
  - A gr.Button exists with label containing 输出文件夹 (or similar).
  - Clicking it calls os.startfile(config.COMFY_OUTPUT_DIR) exactly once.
  - Returns a status string indicating success / path / error.
  - When config.COMFY_OUTPUT_DIR does not exist, returns an error string
    and does NOT call os.startfile.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import gradio as gr

from app import scail2_app, config


def _find_open_output_button(demo):
    """Find the gr.Button whose label mentions output folder."""
    OPEN_KEYS = ("输出文件夹", "打开输出")
    for blk in demo.blocks.values():
        if isinstance(blk, gr.Button):
            label = blk.value or getattr(blk, "label", "") or ""
            if any(k in label for k in OPEN_KEYS):
                return blk
    return None


def test_open_output_button_exists_in_demo():
    """A button to open the ComfyUI output folder exists in build_ui."""
    demo = scail2_app.build_ui()
    btn = _find_open_output_button(demo)
    assert btn is not None, "no button labeled with 输出文件夹 in built demo"


def test_open_output_button_calls_startfile_with_comfy_output_dir():
    """Click handler must call os.startfile(config.COMFY_OUTPUT_DIR) when the dir exists."""
    demo = scail2_app.build_ui()
    btn = _find_open_output_button(demo)
    assert btn is not None, "no button labeled with 输出文件夹"

    # Find the click handler (fn) registered on this button
    fn = _find_click_handler(demo, btn)
    assert fn is not None, f"no click handler on open-output button"

    # Mock os.startfile + Path.exists; run the handler directly.
    with patch.object(scail2_app._os, "startfile") as m_start, \
         patch.object(type(scail2_app.config.COMFY_OUTPUT_DIR), "exists", return_value=True):
        result = fn()
    m_start.assert_called_once()
    args, _ = m_start.call_args
    assert str(args[0]) == str(config.COMFY_OUTPUT_DIR), (
        f"startfile called with {args[0]!r}, expected {config.COMFY_OUTPUT_DIR!r}"
    )
    # Returns a status string mentioning the path
    assert isinstance(result, str)
    assert str(config.COMFY_OUTPUT_DIR) in result or "输出" in result


def test_open_output_button_returns_error_when_dir_missing():
    """When COMFY_OUTPUT_DIR does not exist, handler returns an error string
    and does NOT call os.startfile (avoids FileNotFoundError / ugly dialog)."""
    demo = scail2_app.build_ui()
    btn = _find_open_output_button(demo)
    assert btn is not None
    fn = _find_click_handler(demo, btn)
    assert fn is not None

    with patch.object(scail2_app._os, "startfile") as m_start, \
         patch.object(type(scail2_app.config.COMFY_OUTPUT_DIR), "exists", return_value=False):
        result = fn()
    m_start.assert_not_called()
    assert isinstance(result, str)
    # Error message mentions missing / not found / 找不到 / 不存在
    assert any(k in result for k in ("不存在", "找不到", "missing", "not found")), (
        f"error message unclear: {result!r}"
    )


def _find_click_handler(demo, btn):
    """Find the click handler function registered on a given gr.Button."""
    btn_id = btn._id
    for dep in demo.fns.values():
        cfg = dep.get_config() if hasattr(dep, "get_config") else {}
        for target in (cfg.get("targets") or []):
            if isinstance(target, tuple) and len(target) == 2:
                tid, evname = target
                if tid == btn_id and evname == "click":
                    return dep.fn
    return None

