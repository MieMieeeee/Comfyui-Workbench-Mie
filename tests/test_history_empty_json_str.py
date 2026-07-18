"""History row click + tab.refresh empty placeholders: json_str must be legal JSON.

User bug (2026-07-18): clicking the history tab freezes the page; clicking an entry
pops up "Invalid JSON string: Input is a zero-length, empty document". Both
_make_detail_from_run(None) and _on_history_row_select empty placeholder tuples
shipped json_str="" -> gr.JSON(value="") throws -> red error toast + queue
weirdness ("freeze").

Fix: change empty placeholder json_str from "" to {} (Python dict) so gr.JSON
.postprocess takes the orjson.dumps branch instead of orjson.loads("").

Locked contract:
  1. _make_detail_from_run(None)[2] (json_str) is parseable by json.loads, OR a dict.
  2. _on_history_row_select empty placeholder tuple json_str is parseable, OR a dict.
  3. gr.JSON.postprocess(any of the above) does not raise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import gradio as gr

from app import scail2_app, history

ALL = chr(0x5168) + chr(0x90e8)   # 全部 (filter "all")
FAIL = chr(0x5931) + chr(0x8d25)  # 失败 (filter "failure")


def _parseable_json(s):
    # json_str can be json.loads-parsed, OR it is a dict/list (which gr.JSON accepts directly).
    # gr.JSON accepts Python dict / list / str:
    #   - dict / list: postprocess internally calls json.dumps, never raises on shape.
    #   - str: postprocess calls orjson.loads. Empty string or invalid -> raises.
    if isinstance(s, (dict, list)):
        return True
    if isinstance(s, str):
        try:
            json.loads(s)
            return True
        except (ValueError, TypeError):
            return False
    return False


def _gr_json_accepts(value):
    # gr.JSON.postprocess(value) does not raise in Gradio 6.20.
    c = gr.JSON()
    try:
        c.postprocess(value)
        return True
    except Exception:
        return False


class _FakeSelectData:
    # Stand-in for gr.SelectData; we only need .index for the handler.
    def __init__(self, index):
        self.index = index
        self.value = None
        self.row_value = None
        self.target = None


# --- _make_detail_from_run(None) ---

def test_make_detail_from_run_none_json_str_is_parseable():
    # _make_detail_from_run(None) returns json_str that json.loads accepts (or is a dict).
    # Was returning "" -> gr.JSON raises Invalid JSON.
    _, _, json_str, _ = scail2_app._make_detail_from_run(None)
    assert _parseable_json(json_str), (
        f"_make_detail_from_run(None) returned json_str={json_str!r} not legal JSON;",
        f"gr.JSON.postprocess will raise Invalid JSON string -> red toast",
    )


def test_make_detail_from_run_none_json_str_accepted_by_gr_json():
    # gr.JSON.postprocess(_make_detail_from_run(None)[2]) does not raise.
    _, _, json_str, _ = scail2_app._make_detail_from_run(None)
    assert _gr_json_accepts(json_str), (
        f"gr.JSON.postprocess raised for json_str={json_str!r};",
        f"user will see the red Invalid JSON string toast",
    )


def test_make_detail_from_run_with_run_json_str_still_parseable():
    # _make_detail_from_run(real_run) still returns a parseable json_str (no regression).
    run = {
        "prompt_id": "p0", "created_at": "2026-07-17T10:00:00",
        "preset": "zimage", "status": "success", "duration_sec": 42,
        "prompt_text": "hello",
    }
    _, _, json_str, _ = scail2_app._make_detail_from_run(run)
    assert _parseable_json(json_str)
    parsed = json.loads(json_str)
    assert parsed["prompt_id"] == "p0"
    assert parsed["preset"] == "zimage"


# --- _on_history_row_select empty placeholder ---

def test_on_history_row_select_empty_json_str_parseable():
    # Empty placeholder (cache miss / invalid index / tuple index) json_str is also legal JSON.
    # detail_manifest output safety net.
    scail2_app._HISTORY_RUNS_CACHE.clear()
    # 1) cache miss
    r1 = scail2_app._on_history_row_select(_FakeSelectData(0), ALL, ALL)
    assert _parseable_json(r1[2]), f"cache miss: json_str={r1[2]!r}"
    # 2) invalid index (cache has 1 row, request index=999)
    scail2_app._HISTORY_RUNS_CACHE[(ALL, ALL)] = [{
        "prompt_id": "p0", "created_at": "2026", "preset": "z", "status": "success",
    }]
    r2 = scail2_app._on_history_row_select(_FakeSelectData(999), ALL, ALL)
    assert _parseable_json(r2[2]), f"invalid index: json_str={r2[2]!r}"
    # 3) tuple index (defensive branch)
    r3 = scail2_app._on_history_row_select(_FakeSelectData((0,)), ALL, ALL)
    assert _parseable_json(r3[2]), f"tuple index: json_str={r3[2]!r}"


def test_on_history_row_select_empty_accepted_by_gr_json():
    # gr.JSON accepts the empty placeholder from _on_history_row_select, no raise.
    scail2_app._HISTORY_RUNS_CACHE.clear()
    r = scail2_app._on_history_row_select(_FakeSelectData(0), ALL, ALL)
    assert _gr_json_accepts(r[2]), (
        f"gr.JSON raised (json_str={r[2]!r});",
        f"clicking a row (or cache miss) pops the Invalid JSON string error",
    )


# --- end-to-end: filter to 0 results, then click does not break ---

def test_filter_with_zero_results_then_select_does_not_break_json():
    # Filter combo that yields 0 runs -> click any row -> detail_manifest output must NOT raise.
    # Reproduces the user 2026-07-18 screenshot: empty combo -> click -> red toast.
    scail2_app._HISTORY_RUNS_CACHE.clear()
    with patch.object(scail2_app.history, "list_runs", return_value=[]):
        scail2_app._refresh_history_dataframe("klein_edit", FAIL)
    r = scail2_app._on_history_row_select(_FakeSelectData(0), "klein_edit", FAIL)
    assert _gr_json_accepts(r[2]), (
        f"0-result filter then click: json_str={r[2]!r} not legal JSON;",
        f"gr.JSON raises Invalid JSON string -> user sees red toast",
    )


def test_refresh_history_details_empty_cache_json_str_parseable():
    # _refresh_history_details (cache empty) returns a parseable json_str.
    # tab.select / refresh_btn use this; first opening an empty history tab must not raise.
    scail2_app._HISTORY_RUNS_CACHE.clear()
    _, _, json_str, _, _ = scail2_app._refresh_history_details(ALL, ALL)
    assert _parseable_json(json_str), f"empty cache json_str={json_str!r}"
    assert _gr_json_accepts(json_str), "gr.JSON raised on empty-cache _refresh_history_details"

