"""Regression test: switching workflow must NOT clobber user-edited form values.

bug story (review 2026-07-11):
  1. user submits SCAIL2 motion
  2. switches to SCAIL2 replace to peek at fields
  3. switches back to motion -> wf_radio.change triggers _auto_load_example
     which RESETS the form back to example values
  4. user uploaded reference image, typed prompts all gone

root cause: old _auto_load_example overwrote the active preset on EVERY change
event. fix: module-level set _AUTO_LOADED tracks which presets have been loaded.
first switch -> auto-load + add to set; subsequent switches -> gr.update().
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest
import gradio as gr
from app import scail2_app, config


def _reset_auto_loaded():
    scail2_app._AUTO_LOADED.clear()


def _is_gr_update(x):
    return not isinstance(x, (str, int, float, bool, type(None), list, tuple))


def _realistic_preset_inputs_map():
    workflows = config.list_workflows()
    pmap = {}
    with gr.Blocks():
        for wf in workflows:
            pmap[wf["name"]] = scail2_app._render_workflow_form(wf["name"])
    return pmap


# ---------- core contract ----------

def test_first_switch_auto_loads_example():
    _reset_auto_loaded()
    pmap = _realistic_preset_inputs_map()
    preset_name = config.list_workflows()[0]["name"]
    assert preset_name not in scail2_app._AUTO_LOADED
    result = scail2_app._resolve_auto_load_updates(pmap, preset_name)
    n_active = len(pmap[preset_name])
    active_returns = result[:n_active]
    has_real_value = any(not _is_gr_update(x) for x in active_returns)
    assert has_real_value, (
        "first switch should auto-load example, got all gr.update(): "
        + repr(active_returns)
    )
    assert preset_name in scail2_app._AUTO_LOADED


def test_second_switch_to_same_preset_preserves_user_input():
    _reset_auto_loaded()
    pmap = _realistic_preset_inputs_map()
    preset_name = config.list_workflows()[0]["name"]
    n_active = len(pmap[preset_name])
    scail2_app._resolve_auto_load_updates(pmap, preset_name)  # first
    assert preset_name in scail2_app._AUTO_LOADED
    result2 = scail2_app._resolve_auto_load_updates(pmap, preset_name)  # second
    for i, x in enumerate(result2[:n_active]):
        assert _is_gr_update(x), (
            "second switch to " + preset_name + ", input[" + str(i)
            + "] should be gr.update() (preserve), got " + repr(x)
        )


def test_switch_to_different_preset_auto_loads_it():
    _reset_auto_loaded()
    pmap = _realistic_preset_inputs_map()
    workflows = config.list_workflows()
    assert len(workflows) >= 2, "need at least 2 presets for this test"
    name_a = workflows[0]["name"]
    name_b = workflows[1]["name"]
    scail2_app._resolve_auto_load_updates(pmap, name_a)
    assert name_a in scail2_app._AUTO_LOADED
    assert name_b not in scail2_app._AUTO_LOADED
    result_b = scail2_app._resolve_auto_load_updates(pmap, name_b)
    assert name_b in scail2_app._AUTO_LOADED
    n_b = len(pmap[name_b])
    has_real_value_b = any(not _is_gr_update(x) for x in result_b[:n_b])
    assert has_real_value_b, "first visit to " + name_b + " should auto-load example"


def test_switch_back_preserves_form():
    """A -> B -> A sequence: second A returns gr.update() (preserves first A state)."""
    _reset_auto_loaded()
    pmap = _realistic_preset_inputs_map()
    workflows = config.list_workflows()
    name_a = workflows[0]["name"]
    name_b = workflows[1]["name"]
    n_a = len(pmap[name_a])
    scail2_app._resolve_auto_load_updates(pmap, name_a)  # 1. A
    scail2_app._resolve_auto_load_updates(pmap, name_b)  # 2. B
    result_a_again = scail2_app._resolve_auto_load_updates(pmap, name_a)  # 3. A
    for i, x in enumerate(result_a_again[:n_a]):
        assert _is_gr_update(x), (
            "A->B->A, second A, input[" + str(i) + "] should be gr.update(), got " + repr(x)
        )


def test_non_active_presets_always_get_gr_update():
    _reset_auto_loaded()
    pmap = _realistic_preset_inputs_map()
    workflows = config.list_workflows()
    name_a = workflows[0]["name"]
    name_b = workflows[1]["name"]
    n_b = len(pmap[name_b])
    scail2_app._resolve_auto_load_updates(pmap, name_a)  # A
    result = scail2_app._resolve_auto_load_updates(pmap, name_a)  # A again
    offset = len(pmap[name_a])
    b_returns = result[offset:offset + n_b]
    for i, x in enumerate(b_returns):
        assert _is_gr_update(x), (
            "non-active " + name_b + " input[" + str(i) + "] should be gr.update(), got " + repr(x)
        )


def test_return_length_matches_total_inputs():
    _reset_auto_loaded()
    pmap = _realistic_preset_inputs_map()
    workflows = config.list_workflows()
    total = sum(len(pmap[wf["name"]]) for wf in workflows)
    result = scail2_app._resolve_auto_load_updates(pmap, workflows[0]["name"])
    assert len(result) == total, (
        "return length " + str(len(result)) + " != total " + str(total)
    )


# ---------- upper-layer integration ----------

def test_ex_btn_click_marks_preset_as_loaded():
    import inspect
    src = inspect.getsource(scail2_app._render_workflow_form)
    marker = "if ex_btn is not None:"
    assert src.count(marker) == 1
    block = src[src.index(marker):src.index(marker) + 700]
    assert "_AUTO_LOADED.add(preset_name)" in block, (
        "ex_btn block should add preset_name to _AUTO_LOADED"
    )


def test_last_btn_click_marks_preset_as_loaded():
    import inspect
    src = inspect.getsource(scail2_app._render_workflow_form)
    idx = src.index("def _fill_last_run():")
    end = src.index("last_btn.click", idx)
    block = src[idx:end]
    assert "_AUTO_LOADED.add(preset_name)" in block, (
        "_fill_last_run should add to _AUTO_LOADED, got: " + repr(block)
    )



# ---------- boundaries ----------

def test_invalid_preset_name_does_not_crash():
    _reset_auto_loaded()
    pmap = _realistic_preset_inputs_map()
    result = scail2_app._resolve_auto_load_updates(pmap, "nonexistent_preset")
    for i, x in enumerate(result):
        assert _is_gr_update(x), "invalid preset: input[" + str(i) + "] should be gr.update()"
    assert "nonexistent_preset" not in scail2_app._AUTO_LOADED


def test_AUTO_LOADED_is_module_level_set():
    assert hasattr(scail2_app, "_AUTO_LOADED")
    assert isinstance(scail2_app._AUTO_LOADED, set)
    scail2_app._AUTO_LOADED.add("__test_marker__")
    assert "__test_marker__" in scail2_app._AUTO_LOADED
    scail2_app._AUTO_LOADED.discard("__test_marker__")
