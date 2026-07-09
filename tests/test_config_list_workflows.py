"""config.list_workflows() 的测试。

list_workflows 应返回所有 preset 的有序列表，每项含 UI 渲染所需的元数据。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import config


def test_list_workflows_returns_list():
    wf = config.list_workflows()
    assert isinstance(wf, list)
    assert len(wf) >= 1


def test_list_workflows_sorted_by_order():
    wf = config.list_workflows()
    orders = [w["order"] for w in wf]
    assert orders == sorted(orders)


def test_each_workflow_has_required_fields():
    """每项必须有 name/display_name/category/description/order。"""
    wf = config.list_workflows()
    required = {"name", "display_name", "category", "description", "order"}
    for w in wf:
        missing = required - set(w.keys())
        assert not missing, f"{w.get('name')} missing fields: {missing}"


def test_known_workflows_present():
    """sca12_replace 必须在列表里。"""
    names = [w["name"] for w in config.list_workflows()]
    assert "sca12_replace" in names
    assert "sca12_motion" in names


def test_workflow_name_maps_to_valid_preset():
    """列表里每个 name 都能在 preset_config 里找到对应配置。"""
    for w in config.list_workflows():
        cfg = config.preset_config(w["name"])
        assert "user_facing_inputs" in cfg
        assert "workflow_file" in cfg


def test_list_workflows_is_new_each_call():
    """每次调用返回新 list，调用方改动不影响后续调用。"""
    a = config.list_workflows()
    a.append({"name": "hacked"})
    b = config.list_workflows()
    assert "hacked" not in [w["name"] for w in b]
