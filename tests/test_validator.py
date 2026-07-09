"""workflow_validator.validate 的纯逻辑单测 — 不碰网络。

覆盖：
- 正常通过
- 缺 user_facing 节点
- 缺 inputs 字段
- inputs 非 dict
- 没有 video 输出节点
- params.json 两个真实 preset 都能通过
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import config
from app.workflow_validator import validate, WorkflowValidationError


# --- 最小合成 workflow 工厂 ---

def _video_wf():
    """一个最小合法 workflow：1 个 user_facing 节点 + 1 个视频输出节点。"""
    return {
        "30": {"inputs": {"image": "x.png"}, "class_type": "LoadImage"},
        "9": {"inputs": {"images": ["8", 0]}, "class_type": "VHS_VideoCombine"},
    }


def _spec(node_id="30", field="image", label="参考图"):
    return {"user_facing_inputs": [
        {"node_id": node_id, "field": field, "label": label, "type": "file:image"}
    ]}


# --- 通过用例 ---

def test_validate_ok_minimal():
    validate(_video_wf(), _spec())  # 不抛即通过


def test_validate_real_presets():
    """两个真实 preset 模板都能通过 validator。"""
    for name in ("sca12_replace", "sca12_motion"):
        wf_path = config.workflow_path(name)
        if not wf_path.exists():
            pytest.skip(f"{name}.json not in repo")
        import json
        wf = json.load(wf_path.open(encoding="utf-8"))
        cfg = config.preset_config(name)
        validate(wf, cfg)  # 不抛


# --- 失败用例 ---

def test_validate_missing_node():
    wf = _video_wf()
    cfg = _spec(node_id="999", field="image")
    with pytest.raises(WorkflowValidationError, match="missing node 999"):
        validate(wf, cfg)


def test_validate_missing_field():
    wf = _video_wf()
    cfg = _spec(node_id="30", field="nonexistent")
    with pytest.raises(WorkflowValidationError, match=r"missing inputs\.nonexistent"):
        validate(wf, cfg)


def test_validate_inputs_not_dict():
    wf = _video_wf()
    wf["30"]["inputs"] = ["not", "a", "dict"]
    cfg = _spec(node_id="30", field="image")
    with pytest.raises(WorkflowValidationError, match="inputs is not a dict"):
        validate(wf, cfg)


def test_validate_no_video_output_node():
    wf = {"30": {"inputs": {"image": "x.png"}, "class_type": "LoadImage"}}
    cfg = _spec()
    with pytest.raises(WorkflowValidationError, match="no output node found"):
        validate(wf, cfg)


def test_validate_empty_user_facing_inputs():
    """preset 没有 user_facing_inputs → 报错而不是沉默通过。"""
    wf = _video_wf()
    with pytest.raises(WorkflowValidationError, match="no user_facing_inputs"):
        validate(wf, {"user_facing_inputs": []})
