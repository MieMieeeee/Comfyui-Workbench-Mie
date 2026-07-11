"""回归锁定 2026-07 主题切色 + 运行按钮视觉两个修复的单元测试。

设计要点:
- 这组测试只读 tokens.css 静态文本 + build_ui() 的组件树,不依赖浏览器。
- E2E(主题切换实际让原生按钮变色)放在 tests/test_e2e_browser.py 里。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import gradio as gr

from app import scail2_app

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKENS_CSS = REPO_ROOT / "app" / "static" / "tokens.css"


def _extract_css_block(text: str, selector_prefix: str) -> str | None:
    """找到 "<selector_prefix> { ... }" 的 body(支持嵌套大括号简易情况)。"""
    idx = text.find(selector_prefix + " {")
    if idx < 0:
        idx = text.find(selector_prefix + "{")
    if idx < 0:
        return None
    body_start = text.find("{", idx)
    depth = 0
    for i in range(body_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[body_start + 1:i]
    return None


# ============================================================
# === Gradio 原生组件颜色跟随主题(2026-07 回归锁定)=============
# ============================================================
# 用户报告"保存并测试"等纯 variant=primary 按钮切主题不变色,排查发现
# 两套颜色系统并存:
#   --theme-accent-* (tokens.css 的 CSS 变量) —— 切主题时变
#   THEME = gr.themes.Soft(primary_hue="orange") —— 写死 orange,切主题不变
# Gradio 的 --button-primary-background-fill / --checkbox-background-color-selected
# 等都从 THEME 推到 :root.dark,特异性 (0,1,1),我们之前的 .dark{} (0,1,0) 输掉级联。
# tokens.css 的修复:把覆盖块提高到 :root.dark, :root .dark, body.dark,
# 同等特异性靠后置顺序胜出。下列测试守住这个架构,防以后回归到 .dark{}。


def test_tokens_css_overrides_use_root_dark_selector():
    """Gradio 原生 var 覆盖块必须用 :root.dark, :root .dark (特异性 0,1,1)。

    .dark{} 只有 0,1,0,会被 Gradio 的 :root.dark, :root .dark{} 覆盖。
    这是 2026-07 排查"保存并测试按钮不变色"时确认的真因。
    """
    text = TOKENS_CSS.read_text(encoding="utf-8")
    # 找 --button-primary-background-fill 所在的 :root.dark 块
    m = re.search(r"(:root[^{]*|\.dark[^{]*)\{[^}]*--button-primary-background-fill", text, re.S)
    assert m, "tokens.css 找不到覆盖 --button-primary-background-fill 的块"
    selector = m.group(1)
    assert ":root" in selector, (
        "覆盖块选择器必须是 :root / :root.dark / :root .dark / body.dark 之一,"
        f"不能用 .dark{{}} (特异性不够)。实际: {selector!r}"
    )


def test_tokens_css_maps_primary_button_fill_to_theme_accent():
    """原生 primary 按钮背景必须挂到 --theme-accent-500,跟着切主题变。

    之前是 *primary_500 / *primary_600 (orange),切主题不会变。
    """
    text = TOKENS_CSS.read_text(encoding="utf-8")
    for var in ["--button-primary-background-fill", "--button-primary-background-fill-hover",
                # --button-primary-text-color 走 var(--text-on-accent) (跟背景对比度由主题决定),不挂 --theme-accent-*
                "--button-primary-border-color"]:
        pat = re.escape(var) + r"\s*:\s*var\(--theme-accent-"
        assert re.search(pat, text), f"tokens.css 没把 {var} 挂到 var(--theme-accent-*)"


def test_tokens_css_maps_secondary_button_to_bg_card():
    """原生 secondary 按钮背景必须是 --bg-card (我们的卡片色),不是 Gradio 的白块。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    pat = r"--button-secondary-background-fill\s*:\s*var\(--bg-card\)"
    assert re.search(pat, text), \
        "tokens.css 没把 --button-secondary-background-fill 挂到 var(--bg-card)"


def test_tokens_css_maps_checkbox_selected_to_theme_accent():
    """Checkbox 选中态背景/边框必须挂到 --theme-accent-500,跟着切主题变。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    for var in ["--checkbox-background-color-selected", "--checkbox-border-color-selected"]:
        pat = re.escape(var) + r"\s*:\s*var\(--theme-accent-"
        assert re.search(pat, text), f"tokens.css 没把 {var} 挂到 var(--theme-accent-*)"


def test_tokens_css_maps_radio_color_to_theme_accent():
    """Radio 选中点颜色必须挂到 --theme-accent-500。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    pat = r"--radio-color\s*:\s*var\(--theme-accent-500\)"
    assert re.search(pat, text), "tokens.css 没把 --radio-color 挂到 var(--theme-accent-500)"


def test_tokens_css_class_fallback_overrides_primary_secondary():
    """万一 Gradio 改内部变量名,还要有 .primary / .secondary class 级 !important 兜底。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    # 检查方式更宽松 —— Gradio 选择器可能写 .gradio-container button.primary,
    # .gradio-container .primary { ... } 这种组合写法,regex 写死要求 { 紧跟类名
    # 容易误判。这里只看是不是有覆盖 .primary 的 CSS 块且包含 !important + theme-accent。
    primary_pat = r"\.primary\s*\{[^}]*!important[^}]*var\(--theme-accent-"
    assert re.search(primary_pat, text, re.S), \
        "tokens.css 缺 .primary class 兜底覆盖(必须含 !important + var(--theme-accent-*))"
    secondary_pat = r"\.secondary\s*\{[^}]*var\(--bg-card\)[^}]*!important"
    assert re.search(secondary_pat, text, re.S), \
        "tokens.css 缺 .secondary class 兜底覆盖(必须含 !important + var(--bg-card))"


# ============================================================
# === .is-running 运行中视觉状态 ==============================
# ============================================================
# 用户报告"开始运行之后,按钮应该变成正在运行 或者 变灰吧"。
# 单靠 :disabled 只变灰,文字不变,用户分辨不出"空闲"还是"跑完没成功"。
# 这里加 .is-running 类:active 状态 + spinner + pulse,跟 :disabled 区分。


def test_tokens_css_has_btn_run_primary_is_running_state():
    """.btn-run-primary.is-running 必须存在,运行中视觉态的核心类。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    m = re.search(r"\.btn-run-primary\.is-running\s*\{([^}]+)", text, re.S)
    assert m, "tokens.css 缺 .btn-run-primary.is-running { ... } 块"
    body = m.group(1)
    assert "cursor" in body, ".is-running 没改 cursor,跟 :disabled 视觉一样"
    assert "animation" in body, ".is-running 没动画,pulse/spinner 缺失"
    assert "var(--theme-accent-" in body, \
        ".is-running 背景应该消费 var(--theme-accent-*),切主题才会跟着变"


def test_tokens_css_is_running_has_spinner_keyframes():
    """.btn-run-primary.is-running::before 必须有 spinner (border + 旋转)。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    m = re.search(r"\.btn-run-primary\.is-running::before\s*\{([^}]+)", text, re.S)
    assert m, "tokens.css 缺 .btn-run-primary.is-running::before { ... } 块"
    body = m.group(1)
    assert "border-radius" in body and "50%" in body, \
        "::before 缺圆形 border-radius: 50% (spinner)"
    assert "animation" in body, "::before 缺旋转 animation"
    assert "@keyframes btn-spin" in text, "缺 @keyframes btn-spin"
    assert "@keyframes btn-running-pulse" in text, "缺 @keyframes btn-running-pulse"


def test_tokens_css_disabled_distinct_from_is_running():
    """:disabled 灰显必须跟 .is-running 区分 —— :disabled:not(.is-running) 才是完成态。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    pat = r"\.btn-run-primary:disabled:not\(\.is-running\)"
    assert re.search(pat, text), (
        "缺 .btn-run-primary:disabled:not(.is-running) 区分完成态灰显 vs 运行中态"
    )
    pat2 = r"\.btn-run-primary\[disabled\]:not\(\.is-running\)"
    assert re.search(pat2, text), \
        "缺 .btn-run-primary[disabled]:not(.is-running) 同上属性选择器版本"
