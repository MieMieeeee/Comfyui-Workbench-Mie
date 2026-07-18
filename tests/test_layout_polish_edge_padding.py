"""排版精致化 组6: 文字贴边修复测试。

用户反馈: "导航、文生图 Z-Image-Turbo、输入素材 这些文字紧贴着边界"。

根因 (审计确认):
- .nav-group { padding: 0 } —— "导航"标题 + 工作流列表贴 Group 边。
- .step-card { padding: 0 0 var(--space-4) 0 } —— 左右上是 0, "输入素材" + 表单贴边。
- .section-header —— 只有 padding-bottom, 无左右 padding。
- .gradio-container —— 无 padding 规则, 整个应用内容贴浏览器窗口/外缘。

收敛方向: 给这些容器加合理的内边距 (--space-3 / --space-4), 让文字呼吸。
锁定边界: 不动列 scale 4/7, 不动 .preset-panels-host gap:0。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

TOKENS_CSS = REPO_ROOT / "app" / "static" / "tokens.css"


def _extract_css_block(text: str, selector: str) -> str | None:
    pat = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}", re.S)
    m = pat.search(text)
    return m.group(1) if m else None


def _strip_comments(block: str) -> str:
    """去掉 CSS 注释 (/* ... */), 防止注释里的字面值误导 padding 抽取。"""
    return re.sub(r"/\*.*?\*/", "", block, flags=re.S)


def _padding_values(block: str) -> list[str]:
    """从 CSS block 抽 padding 的 1~4 个值 (token 或字面), 顺序 top right bottom left。
    先去注释, 防止 /* 原 padding: 0 0 ... */ 这种说明文字被误抓。"""
    block = _strip_comments(block)
    m = re.search(r"padding:\s*([^;]+)", block)
    if not m:
        return []
    return m.group(1).strip().split()


# --- .gradio-container 整体边距 ---

def test_gradio_container_has_horizontal_padding():
    """.gradio-container 有水平 padding (整个应用内容不贴浏览器窗口左右缘)。
    审计: 容器无 padding 规则, 内容直接贴外缘, "贴边"感总根源之一。"""
    body = _extract_css_block(TOKENS_CSS.read_text(encoding="utf-8"), ".gradio-container")
    assert body is not None, "缺 .gradio-container 块"
    # 有 padding 声明且第二值 (水平) 走 space token
    pads = _padding_values(body)
    assert pads, f".gradio-container 无 padding 声明 (body={body})"
    assert any("space" in p for p in pads), \
        f".gradio-container padding 没走 --space-* token (pads={pads})"


# --- .nav-group 导航呼吸 ---

def test_nav_group_has_internal_padding():
    """.nav-group 有内边距, "导航"标题和工作流列表不贴 Group 边。
    审计: 原 padding: 0 —— "导航"标题、工作流选项贴 Group 容器边界。"""
    body = _extract_css_block(TOKENS_CSS.read_text(encoding="utf-8"), ".nav-group")
    assert body is not None, "缺 .nav-group 块"
    pads = _padding_values(body)
    assert pads, f".nav-group 无 padding 声明 (body={body})"
    # 至少有水平 padding 且 > 0 (不是 0)
    assert not (len(pads) == 1 and pads[0] == "0"), \
        f".nav-group padding 仍是 0 (贴边); pads={pads}"
    assert any("space" in p and p != "0" for p in pads), \
        f".nav-group padding 没有非零 space token (pads={pads})"


# --- .step-card 表单呼吸 ---

def test_step_card_has_top_and_horizontal_padding():
    """.step-card 有顶部 + 水平 padding, "输入素材"标题和表单不贴卡片边。
    审计: 原 padding: 0 0 var(--space-4) 0 —— 左右上全是 0。"""
    body = _extract_css_block(TOKENS_CSS.read_text(encoding="utf-8"), ".step-card")
    assert body is not None, "缺 .step-card 块"
    pads = _padding_values(body)
    assert pads, f".step-card 无 padding 声明 (body={body})"
    # 解析 4 向 padding (1/2/3/4 值规则)
    if len(pads) == 1:
        top = right = bottom = left = pads[0]
    elif len(pads) == 2:
        top = bottom = pads[0]; right = left = pads[1]
    elif len(pads) == 3:
        top = pads[0]; right = left = pads[1]; bottom = pads[2]
    else:
        top, right, bottom, left = pads[:4]
    # top 不能是 0 (输入素材标题要离卡片顶有距)
    assert top != "0", f".step-card 顶部 padding=0 (标题贴顶); pads={pads}"
    # 水平 (right/left) 不能是 0
    assert right != "0" and left != "0", \
        f".step-card 水平 padding=0 (表单贴左右边); pads={pads}"


# --- .section-header 左右 padding ---

def test_section_header_not_required_horizontal_padding():
    """section-header 的左右 padding 由父 .step-card 提供 (避免双重 padding)。
    这条是文档锁: section-header 本身可不加水平 padding (父容器已加),
    但要确认 step-card 加了之后, section-header 不会被双重缩进。
    实际: 只要 step-card 有 padding 就够了, 这里不强制 section-header 改。"""
    # 占位: 该契约由 test_step_card_has_top_and_horizontal_padding 覆盖。
    # 留这个 test 防止有人误以为 section-header 也要单独加水平 padding。
    body = _extract_css_block(TOKENS_CSS.read_text(encoding="utf-8"), ".section-header")
    assert body is not None, "缺 .section-header 块"


# --- 回归: 改 padding 不破坏 max-width 锁 ---

def test_gradio_container_max_width_still_wide():
    """改 .gradio-container padding 后 max-width 仍 >= 1600 (test_tokens_css_container_max_width 锁)。
    回归锁: 加 padding 时不能误删 max-width。"""
    body = _extract_css_block(TOKENS_CSS.read_text(encoding="utf-8"), ".gradio-container")
    assert body is not None
    m = re.search(r"max-width:\s*(\d+)px", body)
    assert m, f".gradio-container 丢了 max-width (body={body})"
    assert int(m.group(1)) >= 1600, f"max-width={m.group(1)} < 1600 (锁被破坏)"
