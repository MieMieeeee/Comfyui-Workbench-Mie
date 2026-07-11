"""项目规矩：每个 preset 的 `example` 是它的默认参数, 也是 UI 上第一眼看到的。

约定 (review 2026-07-11):
  - demo.load 触发 _auto_load_example(default_wf) -> default preset 表单填 example
  - wf_radio.change 触发 _auto_load_example(name) -> 首次切到 preset 填 example
  - 已有 preset (zimage / sca12_motion / sca12_replace) 都遵循这条
  - 新加 preset 必须填 example, 这是契约

测试覆盖:
  - 所有 preset 都有 example 字段 (非空)
  - example 至少覆盖一个 user_facing_inputs 字段
  - example_to_form_values(preset) 不抛异常
  - 重新跑一遍 example_to_form_values 不会改变 _AUTO_LOADED (用 default 行为)
  - UI 启动时 demo.load 的 lambda 能直接调 (不依赖外部 IO)
"""
from __future__ import annotations
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest
from app import config, scail2_app


# --- 1) 所有 preset 都有非空 example ---

def test_every_preset_has_non_empty_example():
    """所有 preset 必须在 params.json 里填 example 字段, 不能空.

    这是 UI 启动时表单默认填 example 的契约 -- 没有 example 就启动后看到空表单.
    """
    workflows = config.list_workflows()
    missing = []
    for wf in workflows:
        cfg = config.preset_config(wf["name"])
        ex = cfg.get("example")
        if not ex or not isinstance(ex, dict) or len(ex) == 0:
            missing.append(wf["name"])
    assert not missing, (
        f"以下 preset 缺 example 字段: {missing}. "
        f"UI 启动时会拿不到默认参数, 表单空着. "
        f"在 params.json 的 preset 配置里加 example 块 (参照 zimage / sca12_motion)."
    )


# --- 2) example 至少覆盖一个 user_facing_inputs 字段 ---

def test_every_preset_example_covers_at_least_one_user_facing_input():
    """example 必须至少覆盖一个 user_facing_inputs 字段, 否则自动填没意义.

    弱检查: example 里的 key (reference_image / drive_video / ref_prompt / drive_prompt /
    main_prompt / segments / prompt / sizes / frame_load_cap / seed) 至少要有一个.
    """
    KEYS = {
        "reference_image", "drive_video", "ref_prompt", "drive_prompt",
        "main_prompt", "segments", "prompt", "sizes", "frame_load_cap", "seed",
    }
    workflows = config.list_workflows()
    for wf in workflows:
        cfg = config.preset_config(wf["name"])
        ex = cfg.get("example") or {}
        covered = KEYS.intersection(ex.keys())
        assert covered, (
            f"{wf['name']}: example 至少要覆盖一个 user_facing_inputs key "
            f"({sorted(KEYS)}), 当前 example 实际是 {ex!r}"
        )


# --- 3) example_to_form_values 对每个 preset 都能跑通 ---

def test_example_to_form_values_runs_for_every_preset():
    """example_to_form_values(preset) 必须能跑通 (文件可能不在, 但函数不抛)."""
    for wf in config.list_workflows():
        # 不抛即过
        vals = scail2_app.example_to_form_values(wf["name"])
        # 用 flat components 数量 (int_random 拆 2 个, 其它 1 个)
        import gradio as gr
        with gr.Blocks():
            flat = scail2_app._render_workflow_form(wf["name"])
        assert len(vals) == len(flat), (
            f"{wf['name']}: example_to_form_values 返回 {len(vals)} 个值, "
            f"但 flat components 有 {len(flat)} 个. "
            f"int_random 拆 2 个, 其它 1 个; spec 数和 components 数不一定相等."
        )


# --- 4) auto-load example 不污染 _AUTO_LOADED (除了 active preset) ---

def test_auto_load_example_marks_active_preset_only():
    """_resolve_auto_load_updates 调一次后, 只把 active preset 加入 _AUTO_LOADED.
    验证 default 行为契约: 切到 preset -> 加入 -> 切到另一个 -> 两个都在集合里.
    """
    scail2_app._AUTO_LOADED.clear()
    # 模拟 demo.load
    workflows = config.list_workflows()
    first = workflows[0]["name"]
    second = workflows[1]["name"] if len(workflows) >= 2 else None

    # 构造一个 minimal preset_inputs_map
    import gradio as gr
    pmap = {}
    with gr.Blocks():
        for wf in workflows:
            pmap[wf["name"]] = scail2_app._render_workflow_form(wf["name"])
    scail2_app._resolve_auto_load_updates(pmap, first)
    assert first in scail2_app._AUTO_LOADED
    if second:
        assert second not in scail2_app._AUTO_LOADED, (
            f"调 _resolve_auto_load_updates({first!r}) 不应把 {second!r} 加入 _AUTO_LOADED"
        )
    # 清理
    scail2_app._AUTO_LOADED.clear()


# --- 5) demo.load 的 lambda 不抛 (模拟启动) ---

def test_demo_load_lambda_runs_without_error():
    """build_ui 里的 demo.load(lambda: _auto_load_example(default_wf)) 必须能直接调.
    验证 lambda body 在生产环境 (无外部 IO) 下能跑, 不抛异常.

    注: 实际 demo.load 由 Gradio 框架在 SPA 启动时调, 这里用 lambda 直接调模拟.
    """
    scail2_app._AUTO_LOADED.clear()
    workflows = config.list_workflows()
    default_wf = workflows[0]["name"]
    import gradio as gr
    pmap = {}
    with gr.Blocks():
        for wf in workflows:
            pmap[wf["name"]] = scail2_app._render_workflow_form(wf["name"])
    # 模拟 demo.load 的 lambda
    result = scail2_app._resolve_auto_load_updates(pmap, default_wf)
    # 必须返回 list, 长度对齐 total inputs
    total = sum(len(pmap[wf["name"]]) for wf in workflows)
    assert isinstance(result, list)
    assert len(result) == total
    # default preset 应被标记
    assert default_wf in scail2_app._AUTO_LOADED
    scail2_app._AUTO_LOADED.clear()
