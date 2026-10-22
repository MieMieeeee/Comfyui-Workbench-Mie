"""runner 的 bool 型字段 (复选框) patch 行为单测.

SAM3 的「每个检测一个 mask」(individual_masks) 在 UI 里能勾, 但 runner 以前根本没有
bool 分支 —— 值被表单值数组消费掉了, 却从来没进过 replacements, 用户勾了等于没勾.

锁: bool 字段要照实 patch 进节点 (True / False 都算值, False 不能当"没填"),
缺值时退 spec.default.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import config
from app.services import form_schema, runner


def _patch_capture(monkeypatch, captured):
    """统一 mock: patch_workflow 抓 replacements, 其余 scail2_client/history 打桩."""
    monkeypatch.setattr(runner.scail2_client, "patch_workflow",
                        lambda wf, replacements, **kwargs: captured.update(replacements) or wf)
    monkeypatch.setattr(runner.scail2_client, "queue_prompt", lambda wf: ("pid", "cid"))
    monkeypatch.setattr(runner.scail2_client, "build_node_title_map", lambda wf: {})
    monkeypatch.setattr(runner.scail2_client, "start_progress_listener",
                        lambda cid: type("Q", (), {"put": lambda self, value: None})())
    monkeypatch.setattr(runner.scail2_client, "wait_for_completion",
                        lambda *a, **kw: iter(["✅ done"]))
    monkeypatch.setattr(runner.scail2_client, "get_history", lambda pid: {})
    monkeypatch.setattr(runner.scail2_client, "extract_all_image_outputs", lambda hist: [])
    monkeypatch.setattr(runner.scail2_client, "extract_primary_video_output", lambda hist: None)
    monkeypatch.setattr(runner.history, "write_manifest", lambda manifest: None)
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda n: {"nodes": {}})


BOOL_CFG = {"output_kind": "video", "user_facing_inputs": [
    {"node_id": "5", "field": "text", "type": "text"},
    {"node_id": "9", "field": "individual_masks", "type": "bool", "default": False},
]}


def test_run_workflow_patches_bool_true(monkeypatch):
    """勾上了 → 节点里是 True."""
    monkeypatch.setattr(runner.config, "preset_config", lambda n: BOOL_CFG)
    captured = {}
    _patch_capture(monkeypatch, captured)

    list(runner.run_workflow("synthetic", "a prompt", True))

    assert captured["9"] == {"individual_masks": True}


def test_run_workflow_patches_bool_false(monkeypatch):
    """没勾 → 也得 patch False (不能省掉, 工作流自带的值可能是 True)."""
    monkeypatch.setattr(runner.config, "preset_config", lambda n: BOOL_CFG)
    captured = {}
    _patch_capture(monkeypatch, captured)

    list(runner.run_workflow("synthetic", "a prompt", False))

    assert captured["9"] == {"individual_masks": False}


def test_run_workflow_bool_missing_falls_back_to_default(monkeypatch):
    """没传值 → 退 spec.default."""
    cfg = {"output_kind": "video", "user_facing_inputs": [
        {"node_id": "5", "field": "text", "type": "text"},
        {"node_id": "9", "field": "individual_masks", "type": "bool", "default": True},
    ]}
    monkeypatch.setattr(runner.config, "preset_config", lambda n: cfg)
    captured = {}
    _patch_capture(monkeypatch, captured)

    list(runner.run_workflow("synthetic", "a prompt"))

    assert captured["9"] == {"individual_masks": True}


def test_run_image_workflow_patches_bool(monkeypatch):
    """image 路径 (将来有带复选框的文生图) 也要 patch."""
    cfg = {"output_kind": "image", "user_facing_inputs": [
        {"node_id": "5", "field": "text", "type": "text"},
        {"node_id": "13", "field": "sizes", "type": "image_sizes", "default": ["1024x1024"]},
        {"node_id": "9", "field": "individual_masks", "type": "bool", "default": False},
    ]}
    monkeypatch.setattr(runner.config, "preset_config", lambda n: cfg)
    captured = {}
    _patch_capture(monkeypatch, captured)

    list(runner.run_image_workflow("synthetic", "a prompt", ["1024x1024"], True))

    assert captured["9"] == {"individual_masks": True}


def test_sam3_individual_masks_is_patched(monkeypatch):
    """真 preset: sam3_mat_image 的 individual_masks 勾上要进节点."""
    captured = {}
    _patch_capture(monkeypatch, captured)

    values = form_schema.example_to_form_values("sam3_mat_image")
    idx = next(i for i, s in enumerate(config.preset_config("sam3_mat_image")["user_facing_inputs"])
               if s["type"] == "bool")
    values[idx] = True

    # sam3_mat_image 是图生图 (file:image), 走通用 run_workflow 路径
    list(runner.run_workflow("sam3_mat_image", *values))

    spec = next(s for s in config.preset_config("sam3_mat_image")["user_facing_inputs"]
                if s["type"] == "bool")
    assert captured[str(spec["node_id"])][spec["field"]] is True


def test_coerce_bool_handles_json_and_string_forms():
    """表单值可能是 JSON bool / 字符串 "true" / 数字 —— 都要收敛成 bool."""
    assert runner._coerce_bool(True) is True
    assert runner._coerce_bool(False) is False
    assert runner._coerce_bool("true") is True
    assert runner._coerce_bool("True") is True
    assert runner._coerce_bool("1") is True
    assert runner._coerce_bool("false") is False
    assert runner._coerce_bool("") is False
    assert runner._coerce_bool(None, True) is True
    assert runner._coerce_bool(None, False) is False
    assert runner._coerce_bool(0) is False
    assert runner._coerce_bool(1) is True
