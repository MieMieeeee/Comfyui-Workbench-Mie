"""wizard.infer_spec 的 loader 自动识别 → 模型参数类.

用户上传新工作流时, loader 节点的模型字段应被自动标成 type=model/tier=model/高置信度,
这样在向导第 2 步默认勾选、第 3 步归到「模型」层。非模型字段 (如 weight_dtype) 不受影响.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.services import wizard


def test_checkpoint_loader_field_inferred_as_model():
    spec = wizard.infer_spec("97", "ckpt_name", "ace_step.safetensors", "CheckpointLoaderSimple")
    assert spec is not None
    assert spec["type"] == "model"
    assert spec["tier"] == "model"
    assert spec["confidence"] == "high"
    assert spec["default"] == "ace_step.safetensors"
    assert spec["label"] == "大模型"


def test_unet_loader_gguf_inferred_as_model():
    spec = wizard.infer_spec("163", "unet_name", "flux.gguf", "UnetLoaderGGUF")
    assert spec["type"] == "model"
    assert spec["label"] == "扩散模型"


def test_loader_non_model_field_falls_through():
    """loader 节点的非模型字段 (weight_dtype 等) 不应被标成 model, 走通用规则."""
    spec = wizard.infer_spec("16", "weight_dtype", "default", "UNETLoader")
    assert spec is not None
    assert spec["type"] != "model"  # 走 int/text 通用兜底


def test_non_loader_string_stays_text():
    spec = wizard.infer_spec("5", "text", "a prompt", "CLIPTextEncode")
    assert spec["type"] != "model"


def test_lora_loader_only_model_field():
    """LoraLoaderModelOnly 的 lora_name → model; strength_model → 不是."""
    m = wizard.infer_spec("322", "lora_name", "x.safetensors", "LoraLoaderModelOnly")
    assert m["type"] == "model" and m["label"] == "LoRA"
    s = wizard.infer_spec("322", "strength_model", 1.0, "LoraLoaderModelOnly")
    assert s["type"] != "model"
