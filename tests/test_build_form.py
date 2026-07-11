"""_build_form / _build_input_component 的 schema→component 映射测试。

验证表单从 params.json schema 正确生成（这是多工作流 UI 的核心）。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest
import gradio as gr

from app import config, scail2_app


def test_build_form_returns_one_component_per_input():
    """_build_form 返回的组件数 == preset 的 user_facing_inputs 数。"""
    for name in ("sca12_replace", "sca12_motion"):
        cfg = config.preset_config(name)
        comps = scail2_app._build_form(cfg)
        assert len(comps) == len(cfg["user_facing_inputs"]), \
            f"{name}: {len(comps)} comps vs {len(cfg['user_facing_inputs'])} inputs"


def test_build_input_component_file_image():
    spec = {"label": "参考图", "type": "file:image", "node_id": "30", "field": "image"}
    comp = scail2_app._build_input_component(spec)
    assert isinstance(comp, gr.File)


def test_build_input_component_file_video():
    spec = {"label": "驱动视频", "type": "file:video", "node_id": "369", "field": "video"}
    comp = scail2_app._build_input_component(spec)
    assert isinstance(comp, gr.File)


def test_build_input_component_text():
    spec = {"label": "提示词", "type": "text", "node_id": "360", "field": "text",
            "default": "x", "help": "h"}
    comp = scail2_app._build_input_component(spec)
    assert isinstance(comp, gr.Textbox)


def test_build_input_component_int():
    spec = {"label": "段数", "type": "int", "node_id": "479", "field": "int_range_end",
            "min": 1, "max": 12, "default": 8, "step": 1}
    comp = scail2_app._build_input_component(spec)
    assert isinstance(comp, gr.Slider)


def test_build_input_component_unknown_type_raises():
    spec = {"label": "x", "type": "unknown_type", "node_id": "1", "field": "f"}
    with pytest.raises(ValueError, match="unknown input type"):
        scail2_app._build_input_component(spec)


def test_build_input_component_prompt_pool_is_textbox():
    """prompt_pool 主组件是 Textbox（随机按钮在 _render_workflow_form 里额外加）。"""
    spec = {"label": "正向提示词", "type": "prompt_pool", "node_id": "6", "field": "text",
            "default": "x", "help": "h"}
    comp = scail2_app._build_input_component(spec)
    assert isinstance(comp, gr.Textbox)


def test_build_input_component_image_sizes_is_checkboxgroup():
    """image_sizes 主组件是 CheckboxGroup（预设尺寸多选）。"""
    spec = {"label": "输出尺寸", "type": "image_sizes", "node_id": "13", "field": "sizes",
            "default": ["1024x1024"], "presets": ["1024x1024", "1280x720"]}
    comp = scail2_app._build_input_component(spec)
    assert isinstance(comp, gr.CheckboxGroup)
    # Gradio 6 把字符串 choices 存成 (label, value) 元组；提取 value 验证
    choice_values = [c[1] if isinstance(c, (tuple, list)) else c for c in comp.choices]
    assert choice_values == ["1024x1024", "1280x720"]


def test_build_input_component_image_sizes_accepts_labeled_presets():
    """image_sizes 的 presets 数组支持 {label, value} 形式，用于「用途标签化」。

    第四阶段指令 §B：把 output_size 选项升级为带比例与用途说明的表述
    (例：「🎬 1280×720 ｜ 16:9 (横版封面)」)，降低用户扫描成本。

    数据驱动原则：归一化逻辑只在 _build_input_component 内一处做。
    parse_sizes 仍只吃 value（严格 fullmatch），label 不污染解析路径。
    纯字符串 presets 向后兼容（见上一个测试）。
    """
    spec = {
        "label": "输出尺寸", "type": "image_sizes", "node_id": "13", "field": "sizes",
        "default": ["1280x720"],
        "presets": [
            {"label": "🖼 1024×1024 ｜ 1:1 (方图)", "value": "1024x1024"},
            {"label": "🎬 1280×720 ｜ 16:9 (横版封面)", "value": "1280x720"},
        ],
    }
    comp = scail2_app._build_input_component(spec)
    assert isinstance(comp, gr.CheckboxGroup)
    choices = list(comp.choices)
    # value 仍是纯净的 WxH，供 parse_sizes 严格解析
    values = [c[1] if isinstance(c, (tuple, list)) else c for c in choices]
    assert values == ["1024x1024", "1280x720"]
    # label 带用途文案，前端可见
    labels = [c[0] if isinstance(c, (tuple, list)) else c for c in choices]
    assert any("16:9" in lab or "横版" in lab for lab in labels), \
        "label 应带比例/用途说明"
    # 默认值归一后仍是 value（不是 label）
    assert list(comp.value) == ["1280x720"], \
        "default 数组里的值必须是纯净 value，不能是 label"


def test_build_form_zimage_has_3_components():
    """zimage preset 有 3 个 user_facing_inputs（prompt/sizes/seed）。

    seed 是 int_random (Checkbox + Number), 1 个 spec 拆 2 个 component,
    所以 _build_form 返回 4 个 component, 最后一个是 [Checkbox, Number] pair。
    """
    cfg = config.preset_config("zimage")
    # int_random 内部用 gr.Row() 包裹 Checkbox+Number, 必须有 Blocks context
    with gr.Blocks():
        comps = scail2_app._build_form(cfg)
    assert len(comps) == 4
    assert isinstance(comps[0], gr.Textbox)         # prompt_pool
    assert isinstance(comps[1], gr.CheckboxGroup)   # image_sizes
    # int_random: Checkbox (随机) + Number (种子值)
    assert isinstance(comps[2], gr.Checkbox)
    assert isinstance(comps[3], gr.Number)


def test_parse_sizes_preset_string():
    """parse_sizes 把 '1024x1024' 解析成 (1024,1024)。"""
    assert scail2_app.parse_sizes("1024x1024") == (1024, 1024)
    assert scail2_app.parse_sizes("1280x720") == (1280, 720)


def test_parse_sizes_strict_fullmatch():
    """parse_sizes 字符串路径使用严格 fullmatch（不取第一个）。"""
    # 单 size 严格匹配: OK
    assert scail2_app.parse_sizes("800x600") == (800, 600)
    assert scail2_app.parse_sizes("1024x1024") == (1024, 1024)
    # 多 size 逗号串: 拒绝(不在 UI 暴露的契约里; 多 size 走 list 形式)
    assert scail2_app.parse_sizes("1024x1024, 800x600") is None
    # 嵌入文本: 拒绝(以前 search() 会"取到第一个"隐式回退, 现在收掉)
    assert scail2_app.parse_sizes("garbage 1024x1024") is None
    # 缺一维: 拒绝
    assert scail2_app.parse_sizes("1024") is None


def test_parse_sizes_list_input():
    """parse_sizes 接受 list（CheckboxGroup 的值）+ 可选自定义框。"""
    sizes = scail2_app.parse_sizes(["1024x1024", "1280x720"])
    assert sizes == [(1024, 1024), (1280, 720)]


def test_parse_sizes_invalid_returns_none():
    assert scail2_app.parse_sizes("garbage") is None
