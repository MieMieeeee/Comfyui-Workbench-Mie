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


# --- 第四阶段 §A：两栏工作台布局 (左控制栏 + 右预览栏) ---
#
# 把「长表单页面」重组成「左右结构的两栏 AI 创作工作台」。契约:
#   - _render_workflow_form 顶层用 with gr.Row(equal_height=False): 包两个 Column
#   - 左控制栏 gr.Column(scale=4): basic 输入 + 高级参数 Accordion + 🚀 开始运行
#   - 右预览栏 gr.Column(scale=7): 运行日志 Accordion + 输出区 + 🔁 用相同参数再来
#   - theme-injector 仍是 build_ui 顶部全局唯一(不在本函数内),不碰它

def _columns_by_scale(demo, scale):
    """找出 _render_workflow_form 内 scale==指定值的 Column。"""
    return [b for b in demo.blocks.values()
            if isinstance(b, gr.Column) and getattr(b, "scale", None) == scale]


@pytest.mark.parametrize("preset_name", [w["name"] for w in config.list_workflows()])
def test_render_form_has_two_column_workbench(preset_name):
    """每个 preset 表单都应是两栏布局: 左控制栏(scale=4) + 右预览栏(scale=7)。

    review P0 调整后 (第六阶段): 左 scale=4, 右 scale=7。原 §A.1/§A.2/§A.3。
    """
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form(preset_name)
    left = _columns_by_scale(demo, 4)
    right = _columns_by_scale(demo, 7)
    assert len(left) >= 1, f"{preset_name}: 缺左控制栏 gr.Column(scale=4)"
    assert len(right) >= 1, f"{preset_name}: 缺右预览栏 gr.Column(scale=7)"


@pytest.mark.parametrize("preset_name", [w["name"] for w in config.list_workflows()])
def test_run_button_is_primary_and_in_left_column(preset_name):
    """🚀 开始运行 是唯一绝对主操作，必须带 .btn-run-primary 且在左控制栏内。

    视觉焦点唯一性: 主按钮高亮渐变 + glow, 次按钮降级(见 test_css_theming)。
    这里锁定它在左栏 (scale=5 的 Column 上下文里创建)。
    """
    import gradio as gr
    # 用 scale=5 的 Column 作锚点: 检查主按钮的组件 id 落在该 Column 的 children 区间。
    # Gradio 组件创建顺序: 进 with Column 后创建的组件 id 连续递增。
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form(preset_name)
    left_cols = _columns_by_scale(demo, 4)
    assert left_cols, f"{preset_name}: 缺左控制栏"
    left_id = left_cols[0]._id
    # 主按钮带 btn-run-primary 且 label 含「开始运行」
    run_btns = [b for b in demo.blocks.values()
                if isinstance(b, gr.Button)
                and "btn-run-primary" in (getattr(b, "elem_classes", None) or [])
                and "开始运行" in str(b.value or "")]
    assert run_btns, f"{preset_name}: 左栏缺 🚀 开始运行 主按钮"
    # 主按钮 id 必须大于左栏 id (在左栏之后创建) 且小于右栏 id (在右栏之前创建)
    right_cols = _columns_by_scale(demo, 7)
    right_id = right_cols[0]._id
    for btn in run_btns:
        assert left_id < btn._id < right_id, \
            f"{preset_name}: 🚀 开始运行 (id={btn._id}) 不在左控制栏区间 ({left_id}, {right_id})"


@pytest.mark.parametrize("preset_name", [w["name"] for w in config.list_workflows()])
def test_output_and_rerun_are_in_right_column(preset_name):
    """输出区 + 🔁 用相同参数再来 次按钮必须在右预览栏 (scale=6)。

    第四阶段 §A.3: 右侧作品预览栏放结果呈现区 + 次级操作区。
    """
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form(preset_name)
    right_cols = _columns_by_scale(demo, 7)
    assert right_cols, f"{preset_name}: 缺右预览栏"
    right_id = right_cols[0]._id
    # 次按钮带 btn-run-secondary
    rerun_btns = [b for b in demo.blocks.values()
                  if isinstance(b, gr.Button)
                  and "btn-run-secondary" in (getattr(b, "elem_classes", None) or [])]
    assert rerun_btns, f"{preset_name}: 缺 🔁 用相同参数再来 次按钮"
    for btn in rerun_btns:
        assert btn._id > right_id, \
            f"{preset_name}: 🔁 次按钮 (id={btn._id}) 不在右预览栏 (col id={right_id}) 之后"
    # 输出区 (result-area HTML) 也在右栏
    outputs = [b for b in demo.blocks.values()
               if isinstance(b, gr.HTML)
               and "result-area" in (getattr(b, "elem_classes", None) or [])]
    assert outputs, f"{preset_name}: 缺输出区 result-area HTML"
    for out in outputs:
        assert out._id > right_id, \
            f"{preset_name}: 输出区 (id={out._id}) 不在右预览栏 (col id={right_id}) 之后"


@pytest.mark.parametrize("preset_name", [w["name"] for w in config.list_workflows()])
def test_run_log_accordion_is_in_right_column(preset_name):
    """📜 运行日志 折叠面板必须在右预览栏 (指令 §A.3: 默认收起的运行详情折叠面板)。"""
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form(preset_name)
    right_cols = _columns_by_scale(demo, 7)
    assert right_cols, f"{preset_name}: 缺右预览栏"
    right_id = right_cols[0]._id
    log_accs = [b for b in demo.blocks.values()
                if isinstance(b, gr.Accordion) and "运行日志" in str(b.label or "")]
    assert log_accs, f"{preset_name}: 缺 📜 运行日志 Accordion"
    for acc in log_accs:
        assert acc._id > right_id, \
            f"{preset_name}: 📜 运行日志 (id={acc._id}) 不在右预览栏 (col id={right_id}) 之后"


@pytest.mark.parametrize("preset_name", [w["name"] for w in config.list_workflows()])
def test_run_log_accordion_is_below_output_box(preset_name):
    """📜 运行日志 Accordion 必须在 output_box 之后创建 (review 2026-07-14).

    右栏顶部顺序: output_box (预览图) → error_box → re_run_btn → open_dir → 运行日志.
    运行日志默认收起, 不是首屏焦点, 放在 output_box 下方, 让左右两栏顶部
    分别是 status_bar (左) 和 output_box 预览图 (右), 消除顶部高度不齐.
    """
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form(preset_name)
    log_accs = [b for b in demo.blocks.values()
                if isinstance(b, gr.Accordion) and "运行日志" in str(b.label or "")]
    assert log_accs, f"{preset_name}: 缺 📜 运行日志 Accordion"
    outputs = [b for b in demo.blocks.values()
               if isinstance(b, gr.HTML)
               and "result-area" in (getattr(b, "elem_classes", None) or [])]
    assert outputs, f"{preset_name}: 缺输出区 result-area HTML"
    for acc in log_accs:
        for out in outputs:
            assert acc._id > out._id, (
                f"{preset_name}: 📜 运行日志 (id={acc._id}) 必须在 output_box "
                f"(id={out._id}) 之后创建, 当前在之前"
            )


def test_advanced_accordion_is_in_left_column():
    """sca12 的 🔧 高级参数 Accordion 必须在左控制栏 (指令 §A.2)。"""
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("sca12_replace")
    left_cols = _columns_by_scale(demo, 4)
    assert left_cols, "缺左控制栏"
    left_id = left_cols[0]._id
    right_id = _columns_by_scale(demo, 7)[0]._id
    adv_accs = [b for b in demo.blocks.values()
                if isinstance(b, gr.Accordion) and "高级参数" in str(b.label or "")]
    assert adv_accs, "sca12 缺 🔧 高级参数 Accordion"
    for acc in adv_accs:
        assert left_id < acc._id < right_id, \
            f"🔧 高级参数 (id={acc._id}) 不在左控制栏区间 ({left_id}, {right_id})"


def test_basic_inputs_are_in_left_column():
    """basic 输入组件 (上传/提示词/尺寸) 必须在左控制栏 (指令 §A.2)。"""
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("sca12_replace")
    left_cols = _columns_by_scale(demo, 4)
    assert left_cols, "缺左控制栏"
    left_id = left_cols[0]._id
    right_id = _columns_by_scale(demo, 7)[0]._id
    # sca12 有参考图 gr.File (file:image)
    files = [b for b in demo.blocks.values() if isinstance(b, gr.File)]
    assert files, "缺上传组件"
    for f in files:
        assert left_id < f._id < right_id, \
            f"上传组件 (id={f._id}) 不在左控制栏区间 ({left_id}, {right_id})"


# --- 组件结构回归防护 ---
#
# 这组测试锁定 2026-07-10 排查"加载中"时发现的两个结构性 bug:
#   1. theme_injector 在 with gr.Blocks() 之外创建 → 被分配组件 id 但不进 blocks 字典
#      → layout 树引用不存在的组件 → Svelte 前端渲染崩溃
#   2. _build_settings_tab() 没传 theme_injector → fallback 又建一个同 elem_id 组件
#      → 重复 elem_id 干扰前端 DOM 挂载
# 这两个都不会让 Python 报错,只在浏览器里表现为"永久加载中",靠单测守住。

def test_build_ui_no_orphan_layout_references():
    """build_ui() 的 layout 树里每个组件 id 都必须在 demo.blocks 字典里有对应组件。

    回归锁定:theme_injector 曾在 Blocks 上下文外创建 → 它拿到组件 id 但没进 blocks
    字典 → layout 引用了不存在的组件 → 前端 Svelte 渲染卡死。

    检测策略:layout 树里的"叶子"节点(无 children 的)是真正的组件,它们的 id 必须都在
    blocks 字典里。Gradio 的 layout 树还含虚拟容器节点(id=0 根 + 内部布局容器),它们
    不在 blocks 里属正常 —— 通过"只查叶子节点"排除这些虚拟节点。
    另:Gradio 的全局组件 id 计数器在跨测试时会累积,容器节点 id 会漂移,但叶子组件 id
    一定对应 blocks 字典里的真实组件,所以只查叶子是稳的。
    """
    demo = scail2_app.build_ui()
    block_ids = set(demo.blocks.keys())

    # 只收集叶子节点(无 children 或 children 为空的)—— 这些是真实组件
    leaf_ids: set[int] = set()

    def _collect_leaves(node):
        if isinstance(node, dict):
            children = node.get("children", []) or []
            if not children:
                # 叶子节点,但 id=0 是虚拟根,跳过
                if node.get("id", 0) != 0:
                    leaf_ids.add(node["id"])
            else:
                for c in children:
                    _collect_leaves(c)

    _collect_leaves(demo.config["layout"])
    orphan_leaves = leaf_ids - block_ids
    assert not orphan_leaves, (
        f"layout 叶子节点引用了 blocks 字典里不存在的组件 id: {sorted(orphan_leaves)}。"
        f"通常是某个组件在 with gr.Blocks() 上下文外创建导致的。"
    )


def test_build_ui_no_duplicate_elem_ids():
    """build_ui() 的所有组件 elem_id 不能重复。

    回归锁定:_build_settings_tab() 曾未接收 theme_injector 参数,fallback 又建了一个
    同 elem_id="theme-injector" 的组件 → 前端 DOM 挂载异常。
    """
    demo = scail2_app.build_ui()
    from collections import Counter
    elem_ids = [
        str(getattr(b, "elem_id", "") or "")
        for b in demo.blocks.values()
    ]
    dups = {k: v for k, v in Counter(e for e in elem_ids if e).items() if v > 1}
    assert not dups, f"重复的 elem_id (前端 DOM 挂载会冲突): {dups}"


def test_build_ui_theme_injector_exactly_one():
    """elem_id="theme-injector" 的组件必须恰好 1 个。

    0 个 = 主题切换功能丢失(没注入器接收 <style>);
    2 个 = 重复(曾是 settings tab fallback 又建一个)。
    两种都会导致前端异常。
    """
    demo = scail2_app.build_ui()
    injectors = [
        b for b in demo.blocks.values()
        if str(getattr(b, "elem_id", "") or "") == "theme-injector"
    ]
    assert len(injectors) == 1, f"theme-injector 应恰好 1 个, 实际 {len(injectors)} 个"
