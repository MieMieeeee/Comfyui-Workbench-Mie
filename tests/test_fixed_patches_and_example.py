"""fixed_patches + example 加载 + bool type 的测试。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest
import gradio as gr

from app import config, scail2_app


# --- fixed_patches ---

def test_sca12_replace_has_fixed_patches_353_true():
    """sca12_replace(角色替换)的 fixed_patches 应设 node 353 = true。

    node 353 是 PrimitiveBoolean replacement_mode:true = 角色替换, false = 动作迁移。
    (2026-07-10 修正:之前 true/false 含义配反了。)
    """
    cfg = config.preset_config("sca12_replace")
    fp = cfg.get("fixed_patches", {})
    assert "353" in fp
    assert fp["353"]["value"] is True


def test_sca12_motion_has_fixed_patches_353_false():
    """sca12_motion(动作迁移)的 fixed_patches 应设 node 353 = false。"""
    cfg = config.preset_config("sca12_motion")
    fp = cfg.get("fixed_patches", {})
    assert "353" in fp
    assert fp["353"]["value"] is False


def test_run_workflow_applies_fixed_patches():
    """run_workflow 应把 fixed_patches 合并进 replacements。"""
    captured_replacements = {}

    def fake_patch(wf, repl, **kw):
        captured_replacements.update(repl)
        return wf

    ref = Path(__file__).parent / "_dummy_ref.png"
    ref.write_bytes(b"\x89PNG")
    drive = Path(__file__).parent / "_dummy_drive.mp4"
    drive.write_bytes(b"\x00mp4")
    try:
        with patch.object(scail2_app.scail2_client, "upload",
                          side_effect=lambda f, kind="image": {"name": Path(f).name, "subfolder": "", "type": "input"}), \
             patch.object(scail2_app.scail2_client, "load_workflow_template",
                          return_value={"30": {"inputs": {"image": "x"}, "class_type": "LoadImage"},
                                        "353": {"inputs": {"value": False}, "class_type": "PrimitiveBoolean"},
                                        "9": {"inputs": {}, "class_type": "VHS_VideoCombine"}}), \
             patch.object(scail2_app.scail2_client, "patch_workflow", side_effect=fake_patch), \
             patch.object(scail2_app.scail2_client, "queue_prompt", return_value="pid-fake"), \
             patch.object(scail2_app.scail2_client, "wait_for_completion", return_value=iter(["✅ done"])), \
             patch.object(scail2_app.scail2_client, "get_history", return_value={}), \
             patch.object(scail2_app.scail2_client, "extract_primary_video_output", return_value=None):
            # sca12_motion: fixed_patches 353=false (动作迁移模式)
            list(scail2_app.run_workflow("sca12_motion", str(ref), "human", str(drive), "human", "test", 81, 5, 2))
        # patch_workflow 收到的 replacements 应含 node 353 = false
        assert "353" in captured_replacements
        assert captured_replacements["353"]["value"] is False
    finally:
        ref.unlink(missing_ok=True)
        drive.unlink(missing_ok=True)


# --- example 加载 ---

def test_sca12_replace_has_example_field():
    """每个 preset 应有 example 字段（供 UI 加载示例）。"""
    cfg = config.preset_config("sca12_replace")
    ex = cfg.get("example")
    assert ex is not None
    assert "reference_image" in ex
    assert "drive_video" in ex


def test_example_to_form_values_replace():
    """example_to_form_values 把 example 字典映射回表单值列表（按 user_facing_inputs 顺序）。"""
    cfg = config.preset_config("sca12_replace")
    values = scail2_app.example_to_form_values("sca12_replace")
    inputs_spec = cfg["user_facing_inputs"]
    assert len(values) == len(inputs_spec)
    # 第一个是参考图（file:image）→ example.reference_image 解析成绝对路径
    assert values[0] is not None and cfg["example"]["reference_image"] in values[0]
    # 第二个是抠参考图提示词（text）→ example.ref_prompt
    assert values[1] == cfg["example"]["ref_prompt"]


def test_example_to_form_values_zimage():
    """zimage 的 example 只有 prompt + 一个具体 seed，其它用默认。

    seed 是 int_random: example.seed=900259427766747 -> [False, 900259427766747]
    (Checkbox=False 因为给了具体值=固定种子; Number=seed value)。
    所以 values 长度比 user_facing_inputs 多 1 (int_random 拆 2)。
    """
    values = scail2_app.example_to_form_values("zimage")
    cfg = config.preset_config("zimage")
    # user_facing_inputs=3 (prompt/sizes/seed), int_random 拆 2 -> values=4
    assert len(values) == len(cfg["user_facing_inputs"]) + 1
    # prompt_pool 字段应是 example.prompt
    assert cfg["example"]["prompt"] in values[0]
    # seed 部分: [False, 900259427766747]
    assert values[2] is False
    assert values[3] == 900259427766747


# --- A. example 文件值必须 stage 到 CWD 下（修复 gr.File 安全限制 bug）---

def test_example_file_values_staged_under_cwd():
    """file:image/file:video 槽位的 example 值必须 stage 到 CWD 下的缓存目录。

    根因：Gradio 6 gr.File 不接受"应用外部"路径（不在 CWD/cache dir），
    报 "Cannot move ... to the gradio cache dir"。
    修复：_resolve_example_file 把 ComfyUI input 文件复制到 .examples_cache/（CWD 下）。
    """
    cfg = config.preset_config("sca12_replace")
    values = scail2_app.example_to_form_values("sca12_replace")
    inputs_spec = cfg["user_facing_inputs"]
    for spec, v in zip(inputs_spec, values):
        if spec["type"] in ("file:image", "file:video"):
            # 必须是 .examples_cache 下的路径（在 CWD 内，Gradio 接受）
            assert v is None or ".examples_cache" in str(v), \
                f"{spec['label']} example 值应在 .examples_cache 下，实际: {v!r}"


def test_example_file_values_exist_when_input_dir_present():
    """当 ComfyUI input 目录存在时，example 的文件值应真实存在。"""
    if not config.COMFY_INPUT_DIR.exists():
        pytest.skip("ComfyUI input 目录不存在，跳过文件存在性检查")
    cfg = config.preset_config("sca12_replace")
    values = scail2_app.example_to_form_values("sca12_replace")
    inputs_spec = cfg["user_facing_inputs"]
    for spec, v in zip(inputs_spec, values):
        if spec["type"] in ("file:image", "file:video") and v is not None:
            assert Path(v).exists(), f"{spec['label']} example 文件不存在: {v}"


# --- bool type 组件 ---

def test_build_input_component_bool_is_checkbox():
    spec = {"label": "模式", "type": "bool", "node_id": "353", "field": "value",
            "default": False}
    comp = scail2_app._build_input_component(spec)
    assert isinstance(comp, gr.Checkbox)
    assert comp.value is False
