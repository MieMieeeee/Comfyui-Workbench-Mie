"""scail2_client.patch_workflow 的纯逻辑单测 — 不碰网络。

覆盖：
- patch 正确覆盖 inputs 字段
- 目标节点不存在 → WorkflowValidationError
- validate_after=True 时跑 validator
- 浅拷贝不污染原 workflow
- 多字段同时 patch
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_client
from app.workflow_validator import WorkflowValidationError


def _wf():
    """新鲜的最小 workflow，避免测试间共享引用。"""
    return {
        "30": {"inputs": {"image": "orig.png"}, "class_type": "LoadImage"},
        "9": {"inputs": {"images": ["8", 0]}, "class_type": "VHS_VideoCombine"},
    }


def _spec():
    return {"user_facing_inputs": [
        {"node_id": "30", "field": "image", "label": "ref", "type": "file:image"}
    ]}


def test_patch_overwrites_field():
    wf = _wf()
    out = scail2_client.patch_workflow(wf, {"30": {"image": "new.png"}}, _spec())
    assert out["30"]["inputs"]["image"] == "new.png"


def test_patch_missing_target_node_raises():
    wf = _wf()
    with pytest.raises(WorkflowValidationError, match="target node 999 not in workflow"):
        scail2_client.patch_workflow(wf, {"999": {"x": 1}}, _spec())


def test_patch_validate_after_passes():
    """patch 完且 validate_after=True → 调 validator（应通过）。"""
    wf = _wf()
    out = scail2_client.patch_workflow(
        wf, {"30": {"image": "ok.png"}}, _spec(), validate_after=True
    )
    assert out["30"]["inputs"]["image"] == "ok.png"


def test_patch_validate_after_catches_bad_state():
    """patch 后状态不合法（比如清空了 inputs）→ validate 应抛错。"""
    wf = _wf()
    # patch 一个不存在的字段，validator 会因为 user_facing 字段还在而失败吗？
    # user_facing 要求 node 30 有 'image' 字段，我们 patch 时保留它，但故意破坏 video 输出节点
    broken = {k: dict(v) for k, v in wf.items()}
    del broken["9"]  # 删掉视频输出节点
    with pytest.raises(WorkflowValidationError):
        scail2_client.patch_workflow(
            broken, {"30": {"image": "ok.png"}}, _spec(), validate_after=True
        )


def test_patch_does_not_mutate_original():
    """patch 是浅拷贝，原 workflow 不应被改动。"""
    wf = _wf()
    orig_image = wf["30"]["inputs"]["image"]
    scail2_client.patch_workflow(wf, {"30": {"image": "changed.png"}}, _spec())
    assert wf["30"]["inputs"]["image"] == orig_image  # 原件没变


def test_patch_multiple_fields_same_node():
    wf = {
        "13": {"inputs": {"width": 1024, "height": 1024}, "class_type": "EmptySD3LatentImage"},
        "9": {"inputs": {}, "class_type": "VHS_VideoCombine"},
    }
    out = scail2_client.patch_workflow(
        wf, {"13": {"width": 1280, "height": 720}},
        {"user_facing_inputs": [
            {"node_id": "13", "field": "width", "label": "w", "type": "int"},
            {"node_id": "13", "field": "height", "label": "h", "type": "int"},
        ]},
    )
    assert out["13"]["inputs"]["width"] == 1280
    assert out["13"]["inputs"]["height"] == 720


def test_patch_creates_inputs_if_missing():
    """节点没有 inputs 字段时，patch 应自动创建 inputs dict。"""
    wf = {
        "30": {"class_type": "LoadImage"},  # 没有 inputs
        "9": {"inputs": {}, "class_type": "VHS_VideoCombine"},
    }
    out = scail2_client.patch_workflow(wf, {"30": {"image": "x.png"}}, _spec())
    assert out["30"]["inputs"] == {"image": "x.png"}
