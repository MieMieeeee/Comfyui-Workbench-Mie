"""前端表单值 ↔ spec 索引的对齐 (issue #1 回归, Node 驱动真 app.js).

背景: 模板里所有控件都用 spec.idx 读写 formValues (x-model="formValues[idx]"),
但 initPanelScope / _applyFormValues 以前把值按「扁平位置」写进 formValues,
collectFormValues 又按扁平位置读 —— 两套坐标系. 只要 int_random 后面还有别的字段
(int_random 占 2 格), 后面字段的下拉框就显示别的字段的值, 用户改了下拉框还会写错槽.

锁: formValues 的键 = spec 索引; collectFormValues 收回的扁平数组 = spec 顺序
(int_random 占 2 格: 随机勾 + 数值).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import config
from app.services import form_schema

HARNESS = Path(__file__).resolve().parent / "js" / "form_values_harness.js"
APP_JS = REPO_ROOT / "app" / "static" / "app.js"

NODE = shutil.which("node") or shutil.which("nodejs")
pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node 才能跑前端映射测台")

# int_random 后面还有 model 字段的 preset —— 槽位错位就发生在这里
AFFECTED = ["zimage", "Anima_turbo", "qwen_image_2512_4step", "t2i_krea2", "klein_edit"]


def _run_harness(tmp_path, preset, definition, example_values, edits=None):
    payload = {
        "preset": preset,
        "definition": definition,
        "exampleValues": example_values,
        "edits": edits or {},
    }
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [NODE, str(HARNESS), str(payload_path), str(APP_JS)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"node 测台失败:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _flat_positions(definition):
    """每个 spec 在扁平数组里的位置 (int_random 占 2 格) + spec 索引."""
    flat_pos = 0
    out = []
    for idx, spec in enumerate(definition["user_facing_inputs"]):
        if spec["type"] == "int_random":
            out.append((idx, flat_pos, spec))
            flat_pos += 2
        else:
            out.append((idx, flat_pos, spec))
            flat_pos += 1
    return out


@pytest.mark.parametrize("preset", AFFECTED)
def test_form_values_round_trip_keeps_flat_order(tmp_path, preset):
    """initPanelScope 铺进去的值, collectFormValues 收回时必须还是原来的扁平数组."""
    definition = config.preset_config(preset)
    values = form_schema.example_to_form_values(preset)
    out = _run_harness(tmp_path, preset, definition, values)
    assert out["collected"] == values


@pytest.mark.parametrize("preset", AFFECTED)
def test_model_dropdown_bound_to_its_own_spec(tmp_path, preset):
    """模型下拉框 (x-model="formValues[idx]") 必须显示自己那个 spec 的默认值."""
    definition = config.preset_config(preset)
    values = form_schema.example_to_form_values(preset)
    out = _run_harness(tmp_path, preset, definition, values)

    for idx, flat_pos, spec in _flat_positions(definition):
        if spec["type"] != "model":
            continue
        assert out["formValues"][str(idx)] == values[flat_pos], (
            f"{preset}: 模型字段 (spec #{idx}) 拿到的不是自己的默认值")


@pytest.mark.parametrize("preset", AFFECTED)
def test_model_choice_lands_in_its_own_flat_slot(tmp_path, preset):
    """用户在下拉框里换模型 → 扁平数组里属于它的那一格, 不能串到别的槽."""
    definition = config.preset_config(preset)
    values = form_schema.example_to_form_values(preset)

    edits = {}
    expected = {}
    for idx, flat_pos, spec in _flat_positions(definition):
        if spec["type"] != "model":
            continue
        chosen = f"picked\\slot{flat_pos}.safetensors"
        edits[str(idx)] = chosen
        expected[flat_pos] = chosen
    assert expected, "preset 里没有 model 字段, 测试失去意义"

    out = _run_harness(tmp_path, preset, definition, values, edits=edits)
    for flat_pos, chosen in expected.items():
        assert out["collected"][flat_pos] == chosen, (
            f"{preset}: 扁平数组第 {flat_pos} 格不是用户选的模型")


@pytest.mark.parametrize("preset", AFFECTED)
def test_model_select_shows_its_own_model(tmp_path, preset):
    """模型下拉框要显示这个 spec 自己的模型, 不是列表第一项.

    槽位选项 (/api/preset_models) 是异步到的, Alpine 的 x-model 在 <option> 渲染前
    就把值写进 <select> 了 —— 那时选不中任何项, 浏览器只能落回第一项. app.js 的
    _syncModelSelects 负责在选项到位后把值摆正.
    """
    definition = config.preset_config(preset)
    values = form_schema.example_to_form_values(preset)
    out = _run_harness(tmp_path, preset, definition, values)

    expected = {}
    for idx, flat_pos, spec in _flat_positions(definition):
        if spec["type"] == "model":
            expected[str(idx)] = values[flat_pos]
    assert expected, "preset 里没有 model 字段, 测试失去意义"

    got = {s["idx"]: s["value"] for s in out["selects"]}
    for idx, want in expected.items():
        assert got.get(idx) == want, (
            f"{preset}: 模型下拉框 (spec #{idx}) 显示的是 {got.get(idx)!r}, 应为 {want!r}")


def test_bool_checkbox_round_trip(tmp_path):
    """复选框: 勾上 → 扁平数组里是 true; 不勾 → 是 false (不能当成缺值丢掉)."""
    definition = {"user_facing_inputs": [
        {"node_id": "5", "field": "text", "type": "text", "default": "prompt"},
        {"node_id": "9", "field": "individual_masks", "type": "bool", "default": False},
    ]}
    values = ["prompt", False]

    unchecked = _run_harness(tmp_path, "synthetic", definition, values)
    assert unchecked["collected"] == ["prompt", False]

    checked = _run_harness(tmp_path, "synthetic", definition, values, edits={"1": True})
    assert checked["collected"] == ["prompt", True]
