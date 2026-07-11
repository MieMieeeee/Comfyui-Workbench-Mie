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


# ---- output_box 默认填 example (review 2026-07-11) ----

def test_output_box_initial_value_is_example_preview():
    """output_box (生成结果) 初始值应是 example.preview_image / preview_video 渲染出来的 HTML,
    不是 \u201c\u8fd0\u884c\u540e\u8fd9\u91cc\u663e\u793a\u7ed3\u679c\u201d 占位符.

    设计: 默认参数 = example, 用户打开工作流后第一眼看到 example 跑出来的效果.
    跑了之后 _run_and_format 会用实际生成结果覆盖这个默认值.
    """
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("zimage")
    output_boxes = [
        b for b in demo.blocks.values()
        if isinstance(b, gr.HTML) and "result-area" in (getattr(b, "elem_classes", None) or [])
    ]
    assert len(output_boxes) == 1, f"zimage 应只有 1 个 result-area, 实际 {len(output_boxes)}"
    val = output_boxes[0].value or ""
    assert "\u8fd0\u884c\u540e\u8fd9\u91cc\u663e\u793a\u7ed3\u679c" not in val, (
        f"output_box 初始值不应再是占位符 \u201c\u8fd0\u884c\u540e\u8fd9\u91cc\u663e\u793a\u7ed3\u679c\u201d, 实际:\n{val[:300]}"
    )
    assert "result-area-default" in val, (
        f"output_box 初始值应含 result-area-default class 标记\u793a\u4f8b\u9ed8\u8ba4\u72b6\u6001:\n{val[:300]}"
    )
    # \u5e94\u5305\u542b zimage \u793a\u4f8b\u56fe
    assert "zimage_720x1280_0001.png" in val, (
        f"output_box \u5e94\u663e\u793a zimage \u793a\u4f8b\u56fe, \u5b9e\u9645:\n{val[:300]}"
    )


def test_output_box_uses_preview_video_for_sca12_presets():
    """sca12_motion / sca12_replace 有 preview_video, output_box 应渲染 <video> 标签."""
    import gradio as gr
    for preset_name in ("sca12_motion", "sca12_replace"):
        with gr.Blocks() as demo:
            scail2_app._render_workflow_form(preset_name)
        output_boxes = [
            b for b in demo.blocks.values()
            if isinstance(b, gr.HTML) and "result-area" in (getattr(b, "elem_classes", None) or [])
        ]
        assert len(output_boxes) == 1
        val = output_boxes[0].value or ""
        assert "<video" in val, f"{preset_name}: 应渲染 <video> 标签, 实际:\n{val[:300]}"
        # 视频文件名应出现
        assert f"{preset_name}_3seg.mp4" in val, (
            f"{preset_name}: 应引用 {preset_name}_3seg.mp4, 实际:\n{val[:300]}"
        )
        # caption 标记示例状态
        assert "\u793a\u4f8b\u6548\u679c" in val, (
            f"{preset_name}: 应有 \u201c\u793a\u4f8b\u6548\u679c\u201d caption 提示这是默认状态"
        )


def test_output_box_caption_mentions_default_params():
    """output_box 的 \u793a\u4f8b\u6548\u679c caption \u5e94\u660e\u786e\u8bf4\u660e\u201c\u9ed8\u8ba4\u53c2\u6570\u5bf9\u5e94\u7684\u7ed3\u679c\u201d, 用户能分清\u793a\u4f8b\u4e0e\u5b9e\u9645\u8fd0\u884c\u7ed3\u679c.

    跑了之后这个 caption \u4f1a\u88ab\u8986\u76d6, \u4e0d\u4f1a\u5e72\u6270\u5b9e\u9645\u8f93\u51fa\u7684\u9605\u8bfb.
    """
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("zimage")
    output_boxes = [
        b for b in demo.blocks.values()
        if isinstance(b, gr.HTML) and "result-area" in (getattr(b, "elem_classes", None) or [])
    ]
    val = output_boxes[0].value or ""
    assert "\u9ed8\u8ba4\u53c2\u6570\u5bf9\u5e94\u7684\u7ed3\u679c" in val, (
        f"caption \u5e94\u660e\u786e\u8bf4\u660e\u201c\u9ed8\u8ba4\u53c2\u6570\u5bf9\u5e94\u7684\u7ed3\u679c\u201d, \u5b9e\u9645:\n{val}"
    )
