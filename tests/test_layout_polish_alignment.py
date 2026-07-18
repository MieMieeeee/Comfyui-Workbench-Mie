"""排版精致化 组3: 左右栏顶部对齐测试。

审计发现:
- 左栏顶部 **导航** 小标签 vs 右栏 ### (现 ##) 工作流标题带 16px+ margin → 顶部错位 ~20px。
- equal_height=False → 运行按钮和输出区 Y 坐标飘 (首次成功 re_run_btn 出现, 右栏长一截,
  运行按钮原本对齐输出区中部, 之后错位)。

收敛方向:
- _render_workflow_form 的 gr.Row 用 equal_height=True (左右子栏等高, 不再 Y 飘)。
- h2 顶部 margin 收敛, 跟左栏 nav-group 顶部基线对齐 (不制造额外 offset)。

锁定边界 (不动):
- 列 scale 4/7 (test_e2e_render.py 锁)。
- 列成员 _id 顺序 (test_e2e_render.py 锁)。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import re
import pytest

from app import scail2_app

TOKENS_CSS = REPO_ROOT / "app" / "static" / "tokens.css"


def test_workflow_form_row_uses_equal_height_true():
    """_render_workflow_form 的 gr.Row 用 equal_height=True。
    审计: equal_height=False 让左右子栏不等高, 运行按钮 (左) 和输出区 (右) Y 坐标飘。
    equal_height=True 让两栏顶部对齐, 运行按钮锚定在左栏底部, 不再随右栏内容增长而错位。"""
    import inspect
    src = inspect.getsource(scail2_app._render_workflow_form)
    # 找两栏 Row 那行 (含 scale 的 Column 在它里面)
    # 原代码: with gr.Row(equal_height=False):
    assert "equal_height=True" in src, \
        "_render_workflow_form 的 gr.Row 没用 equal_height=True (左右栏不等高会 Y 错位)"
    assert "equal_height=False" not in src, \
        "_render_workflow_form 还有 equal_height=False"


def test_h2_top_margin_aligned_with_column_baseline():
    """h2 顶部 margin 不能太大 (跟左栏 nav-group 顶部基线对齐)。
    审计: 原 h3 margin top=--space-4 (16px), 加上 Gradio block chrome 让右栏内容
    比左栏 **导航** 标签低 ~20px。收敛 h2 顶部 margin 到 <= --space-3 (12px),
    跟 nav-group 顶部基线尽量齐。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    m = re.search(r"(?:\.prose h2|h2)\s*\{([^}]*)\}", text, re.S)
    assert m, "找不到 h2 CSS 规则"
    body = m.group(1)
    mm = re.search(r"margin:\s*([^;]+)", body)
    assert mm, f"h2 margin 缺失 (body={body})"
    margin_val = mm.group(1)
    # 取 margin 第一个 token (top), 检查它引用的 space token <= --space-3
    small_tokens = ("--space-1", "--space-2", "--space-3")
    big_tokens = ("--space-4", "--space-5", "--space-6", "--space-8", "--space-10", "--space-12")
    has_big = any(t in margin_val.split()[0] for t in big_tokens)
    has_small = any(t in margin_val.split()[0] for t in small_tokens)
    assert not has_big, \
        f"h2 顶部 margin 太大 (含 --space-4+; margin={margin_val}); 应 <= --space-3"
    assert has_small or margin_val.split()[0] == "0", \
        f"h2 顶部 margin 没收敛到小 token (margin={margin_val}); 应 --space-1/2/3 或 0"


def test_two_column_layout_preserved():
    """回归锁: equal_height 改了, 但两栏结构 (scale 4 + scale 7) 必须保留。
    test_e2e_render.py 已锁 scale 值, 这里再锁 _render_workflow_form 源码里有
    scale=4 和 scale=7 的 Column (防止重构时误删)。"""
    import inspect
    src = inspect.getsource(scail2_app._render_workflow_form)
    assert "scale=4" in src, "_render_workflow_form 缺左栏 scale=4"
    assert "scale=7" in src, "_render_workflow_form 缺右栏 scale=7"
