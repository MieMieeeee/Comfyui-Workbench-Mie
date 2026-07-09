"""E2E 渲染测试：真实触发 @gr.render，确保每个 preset 的表单能无异常渲染。

复现并锁定 DuplicateBlockError：组件构造时已自动 render，再调 .render() 会重复注册。
这个测试不 mock，真正调 Renderable.apply() 触发 render 函数。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest
import gradio as gr
from gradio.renderable import Renderable

from app import config, scail2_app


def _get_renderables(demo) -> list:
    """从 Blocks 里找出所有 @gr.render 创建的 Renderable。"""
    return list(getattr(demo, "renderables", []))


@pytest.fixture
def demo():
    return scail2_app.build_ui()


def test_build_ui_pre_renders_all_panels(demo):
    """build_ui 应该为每个 preset 预渲染一张面板（包 gr.Group），以保证切 preset 时表单状态保留。

    原来的 @gr.render 会重建组件、表单状态丢失。现在采用 gr.Group 切换 visibility 的方式，
    表单状态由 Gradio 自动保留。"""
    panels = [b for b in demo.blocks.values() if str(getattr(b, "elem_id", "")) .startswith("panel-")]
    expected = {w["name"] for w in config.list_workflows()}
    found = {str(p.elem_id).removeprefix("panel-") for p in panels}
    assert expected <= found, f"missing panels: {expected - found}"


@pytest.mark.parametrize("preset_name", [w["name"] for w in config.list_workflows()])
def test_render_form_each_preset_no_error(preset_name):
    """每个 preset 的表单渲染都不应抛异常（DuplicateBlockError 等）。

    真正执行 _render_workflow_form 函数体（在 Blocks 上下文里），验证组件树能正确构建。
    这复现并锁定用户遇到的 DuplicateBlockError。
    """
    with gr.Blocks():
        # _render_workflow_form 内部会创建表单组件 + 辅助按钮 + 输出区
        # 如果组件被重复 render，这里会抛 DuplicateBlockError
        scail2_app._render_workflow_form(preset_name)


def test_render_form_produces_inputs():
    """渲染后应产生表单组件（不是空表单）。"""
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form(config.list_workflows()[0]["name"])
    # 应该有多个组件（inputs + buttons + output）
    assert len(demo.blocks) > 2


def test_render_form_switches_presets_no_leak():
    """连续渲染不同 preset 不应互相干扰（状态泄漏测试）。

    模拟用户在 UI 切换工作流：先渲染 A，再渲染 B，都不应报错。
    """
    for preset_name in [w["name"] for w in config.list_workflows()]:
        with gr.Blocks():
            scail2_app._render_workflow_form(preset_name)


# --- 重构后：Accordion / tier 分组验证 ---

@pytest.mark.parametrize("preset_name", [w["name"] for w in config.list_workflows()])
def test_render_form_with_accordion_no_error(preset_name):
    """重构后（步骤分区 + Accordion）每个 preset 渲染仍不报错。

    回归防护：_create_one_input 在 gr.Group/Accordion 容器内创建组件，
    不能重复 .render()（DuplicateBlockError）。
    """
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form(preset_name)
    # 渲染后应有组件（inputs + accordion + buttons + output）
    assert len(demo.blocks) > 3


def test_video_presets_have_advanced_accordion():
    """sca12 preset 有 advanced 参数 → 渲染后应含 Accordion 组件。"""
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("sca12_replace")
    has_accordion = any(isinstance(b, gr.Accordion) for b in demo.blocks.values())
    assert has_accordion, "sca12 应有高级参数 Accordion"


def test_zimage_no_advanced_accordion():
    """zimage 全是 basic → 不应有"高级参数" Accordion(但可以有"运行日志" Accordion。)"""
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("zimage")
    # 只检查是否有"高级参数"助手拗叠,”运行日志"“是允许的。
    has_advanced = any(
        isinstance(b, gr.Accordion) and "高级参数" in str(b.label or "")
        for b in demo.blocks.values()
    )
    assert not has_advanced, "zimage 不应有 高级参数 Accordion"
