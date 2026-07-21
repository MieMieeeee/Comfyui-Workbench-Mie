"""排版精致化 组2: 视觉权重层级测试。

审计发现:
- h3 工作流标题用 --text-secondary (灰), 下面 **① 输入素材** 用 --text-primary (白)
  → 副标题比标题还醒目, 视觉权重倒置。
- 工作流标题是 h3, 全局 h1→h3 跳过 h2, 层级断层。
- .btn-run-primary 15px/600 vs secondary 14px/500 只差 1px+1 级, 主按钮没拉开。

收敛方向:
- h3 颜色 --text-secondary → --text-primary (标题不该比 section header 暗)。
- 工作流标题 ### (h3) → ## (h2, 20px/600), 给 h1(app)→h2(workflow)→section 清晰层级。
- .btn-run-primary 字号 → --text-lg (16px), 字重 → 700。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app

TOKENS_CSS = REPO_ROOT / "app" / "static" / "tokens.css"


def _extract_css_block(text: str, selector: str) -> str | None:
    """从 CSS 抠出选择器块内容 (大括号内), 支持多选择器组合 (.a, .b { })。"""
    # 转义 selector 里的特殊字符, 允许前面有任意字符 (多选择器), 后面跟 {
    pat = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}", re.S)
    m = pat.search(text)
    return m.group(1) if m else None


# --- h3 提亮 ---

def test_h3_uses_text_primary_not_secondary():
    """h3 CSS 的 color 必须用 --text-primary (不是 secondary)。
    审计: 标题用灰色 --text-secondary, 下面 section-header 用 --text-primary,
    副标题比标题醒目, 视觉权重倒置。"""
    body = _extract_css_block(TOKENS_CSS.read_text(encoding="utf-8"), ".gradio-container h3")
    # h3 可能跟 .prose h3 组合在同一个规则, 抓任一含 h3 的块
    if body is None:
        text = TOKENS_CSS.read_text(encoding="utf-8")
        # 抓 "h3 {" 或 ".prose h3 {" 块
        m = re.search(r"(?:\.prose h3|h3)\s*\{([^}]*)\}", text, re.S)
        assert m, "找不到 h3 CSS 规则"
        body = m.group(1)
    assert "--text-primary" in body, f"h3 颜色没用 --text-primary (body={body})"
    assert "--text-secondary" not in body, f"h3 仍在用 --text-secondary (灰, 比标题暗)"


# --- 工作流标题升 h2 ---

def test_workflow_title_is_h2_not_h3():
    """_render_workflow_form 的工作流标题用 ## (h2), 不是 ### (h3)。
    审计: 全局 h1(app)→h3(workflow) 跳过 h2, 层级断层。提级到 h2 给清晰三级:
    h1=app, h2=workflow, section-header=form 小节。"""
    import inspect
    src = inspect.getsource(scail2_app._render_workflow_form)
    # 工作流标题是 gr.Markdown(f"### {display_name}..."), 应改成 ##
    assert '"## ' in src or "'## " in src, \
        "_render_workflow_form 工作流标题没用 ## (h2); 找 '### ' 说明还是 h3"
    assert '"### ' not in src and "'### " not in src, \
        "_render_workflow_form 还有 ### (h3) 工作流标题, 应提级到 ## (h2)"


# --- 主按钮字号字重拉开 ---

def test_btn_run_primary_font_size_is_text_lg():
    """.btn-run-primary 字号用 --text-lg (16px), 不再用 --text-md (已删) / --text-base。
    主按钮跟 secondary (base=14px) 拉开 2px, 视觉上是绝对主操作。"""
    body = _extract_css_block(TOKENS_CSS.read_text(encoding="utf-8"), ".btn-run-primary")
    assert body is not None, "缺 .btn-run-primary 块"
    assert "--text-lg" in body, f".btn-run-primary 字号没用 --text-lg (body={body})"


def test_btn_run_primary_font_weight_700():
    """.btn-run-primary 字重 700 (比 secondary 的 500 重两级), 强化主操作感。"""
    body = _extract_css_block(TOKENS_CSS.read_text(encoding="utf-8"), ".btn-run-primary")
    assert body is not None
    assert "font-weight: 700" in body, f".btn-run-primary 字重不是 700 (body={body})"


def test_btn_run_secondary_still_lower_weight_than_primary():
    """secondary 字重仍 < primary, 保持层级 (primary 700, secondary 500)。
    向后兼容锁: 不能让 secondary 抢主按钮的视觉权重。"""
    prim = _extract_css_block(TOKENS_CSS.read_text(encoding="utf-8"), ".btn-run-primary") or ""
    sec = _extract_css_block(TOKENS_CSS.read_text(encoding="utf-8"), ".btn-run-secondary") or ""
    pw = re.search(r"font-weight:\s*(\d+)", prim)
    sw = re.search(r"font-weight:\s*(\d+)", sec)
    assert pw and sw, "primary/secondary 缺 font-weight"
    assert int(pw.group(1)) > int(sw.group(1)), \
        f"primary 字重 {pw.group(1)} 没比 secondary {sw.group(1)} 重"
