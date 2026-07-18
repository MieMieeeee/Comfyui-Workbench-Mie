"""run-status-bar 百分比胶囊测试 (CSS + 渲染)。

覆盖：
- tokens.css 有 .run-status-progress 块 (主题色边框 + 半透明填充)
- _render_status_html 接 progress_str 时渲染 <span class="run-status-progress">
- 不传 progress_str 时跟现状一致 (无 progress span, 向后兼容)

为什么：P0/P2/P3 让 gr.Progress 用真实 step %。状态条 (status_bar) 也要显示
同一个百分比, 让"瞄一眼顶部就知道还差多少"成立 (单行 flex, 百分比胶囊)。
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


def _extract_css_block(text: str, selector: str) -> str | None:
    """从 CSS 文本里抠出某个选择器的块内容 (大括号内)。找不到返回 None。"""
    pat = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}", re.S)
    m = pat.search(text)
    return m.group(1) if m else None


# --- CSS ---

def test_tokens_css_has_run_status_progress_block():
    """.run-status-progress 胶囊样式块必须存在。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    assert _extract_css_block(text, ".run-status-progress") is not None, \
        "tokens.css 缺 .run-status-progress 块"


def test_run_status_progress_uses_theme_accent():
    """胶囊用主题色 (--theme-accent-*), 跟运行态 run-status-bar 视觉一致。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_css_block(text, ".run-status-progress")
    assert body is not None, "缺 .run-status-progress 块"
    assert "--theme-accent" in body, \
        ".run-status-progress 必须消费 --theme-accent-* (跟 running 态边框同色)"


def test_run_status_progress_is_compact():
    """胶囊是紧凑的 (font-mono / 小字号), 不抢状态条主信息 (label + msg) 的视觉。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_css_block(text, ".run-status-progress")
    assert body is not None
    # 复用 run-status-elapsed 的紧凑特征: mono 字体 + 小字号 + flex-shrink
    assert "mono" in body or "font-mono" in body or "--text-xs" in body, \
        ".run-status-progress 应是紧凑 mono 小字号 (跟 .run-status-elapsed 同风格)"


# --- _render_status_html 渲染 ---

def test_render_status_html_renders_progress_capsule():
    """传 progress_str="60%" -> HTML 含 <span class="run-status-progress">60%</span>。"""
    html = scail2_app._render_status_html("running", "KSampler 12/20", elapsed_str="00:42", progress_str="60%")
    assert "run-status-progress" in html
    assert "60%" in html


def test_render_status_html_no_progress_by_default():
    """不传 progress_str -> 无 progress span (向后兼容锁, 现有调用方不传)。"""
    html = scail2_app._render_status_html("running", "running…")
    assert "run-status-progress" not in html


def test_render_status_html_empty_progress_no_span():
    """progress_str='' -> 不渲染空胶囊 (避免显示空的百分比框)。"""
    html = scail2_app._render_status_html("running", "running…", progress_str="")
    assert "run-status-progress" not in html


def test_render_status_html_progress_after_elapsed():
    """胶囊位置在 elapsed 之后 (最右侧), 跟用户选择的"百分比胶囊"布局一致。
    单行 flex: icon · label · msg · elapsed · progress。"""
    html = scail2_app._render_status_html(
        "running", "KSampler 12/20", elapsed_str="00:42", progress_str="60%",
    )
    elapsed_pos = html.find("run-status-elapsed")
    progress_pos = html.find("run-status-progress")
    assert elapsed_pos != -1 and progress_pos != -1
    assert progress_pos > elapsed_pos, "progress 胶囊应在 elapsed 之后 (最右)"
