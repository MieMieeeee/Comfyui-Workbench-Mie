"""runner 的「模型」参数类 (type=model) patch 行为单测.

model 条目应像 select 一样把用户选的模型文件名 patch 进 loader 节点;
空值时退 spec.default (工作流自带模型), 不用 DEFAULT_PROMPT_TEXT 兜底 (会把运行打挂).
覆盖 video 路径 (run_workflow) 和 image 路径 (run_image_workflow).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.services import runner


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


def test_run_workflow_patches_model_override(monkeypatch):
    """video 路径: 用户选了别的模型 → patch 进 loader 节点."""
    cfg = {"output_kind": "video", "user_facing_inputs": [
        {"node_id": "5", "field": "text", "type": "text", "tier": "basic"},
        {"node_id": "16", "field": "unet_name", "type": "model", "tier": "model",
         "default": "Z\\orig.safetensors"},
    ]}
    graph = {
        "5": {"inputs": {"text": ""}, "class_type": "CLIPTextEncode"},
        "16": {"inputs": {"unet_name": "Z\\orig.safetensors"}, "class_type": "UNETLoader"},
    }
    monkeypatch.setattr(runner.config, "preset_config", lambda n: cfg)
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda n: graph)
    captured = {}
    _patch_capture(monkeypatch, captured)

    list(runner.run_workflow("synthetic", "a prompt", "Z\\chosen.safetensors"))

    assert captured["16"] == {"unet_name": "Z\\chosen.safetensors"}
    # text 也应正常 patch (没被 model 槽位吞掉)
    assert captured["5"] == {"text": "a prompt"}


def test_run_workflow_model_empty_falls_back_to_default(monkeypatch):
    """model 值为空 → 退 spec.default (= 工作流自带模型), 不退 DEFAULT_PROMPT_TEXT."""
    cfg = {"output_kind": "video", "user_facing_inputs": [
        {"node_id": "16", "field": "unet_name", "type": "model",
         "default": "Z\\orig.safetensors"},
    ]}
    graph = {"16": {"inputs": {"unet_name": "Z\\orig.safetensors"}, "class_type": "UNETLoader"}}
    monkeypatch.setattr(runner.config, "preset_config", lambda n: cfg)
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda n: graph)
    captured = {}
    _patch_capture(monkeypatch, captured)

    list(runner.run_workflow("synthetic", ""))  # model 值传空串

    assert captured.get("16") == {"unet_name": "Z\\orig.safetensors"}
    assert "A person walking" not in str(captured)  # 不能漏进模型字段


def test_run_image_workflow_patches_model(monkeypatch):
    """image 路径 (zimage/qwen 等 T2I): 模型覆盖也要 patch, 且每个尺寸都带."""
    cfg = {"output_kind": "image", "user_facing_inputs": [
        {"node_id": "5", "field": "text", "type": "text"},
        {"node_id": "16", "field": "unet_name", "type": "model", "default": "Z\\orig.safetensors"},
    ]}
    graph = {
        "5": {"inputs": {"text": ""}, "class_type": "CLIPTextEncode"},
        "16": {"inputs": {"unet_name": "Z\\orig.safetensors"}, "class_type": "UNETLoader"},
    }
    monkeypatch.setattr(runner.config, "preset_config", lambda n: cfg)
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda n: graph)
    captured = {}
    _patch_capture(monkeypatch, captured)

    list(runner.run_image_workflow("synthetic", "a red car", "Z\\chosen.safetensors"))

    assert captured["16"] == {"unet_name": "Z\\chosen.safetensors"}


def test_run_image_workflow_model_without_value_uses_default(monkeypatch):
    """image 路径: model 没传值 → 用 spec.default, 不留空打挂 loader."""
    cfg = {"output_kind": "image", "user_facing_inputs": [
        {"node_id": "5", "field": "text", "type": "text"},
        {"node_id": "16", "field": "unet_name", "type": "model", "default": "Z\\orig.safetensors"},
    ]}
    graph = {"5": {"inputs": {}}, "16": {"inputs": {"unet_name": "Z\\orig.safetensors"}}}
    monkeypatch.setattr(runner.config, "preset_config", lambda n: cfg)
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda n: graph)
    captured = {}
    _patch_capture(monkeypatch, captured)

    list(runner.run_image_workflow("synthetic", "prompt", ""))

    assert captured.get("16") == {"unet_name": "Z\\orig.safetensors"}
