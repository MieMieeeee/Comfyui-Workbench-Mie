"""Vercel Web Interface Guidelines 合规测试 (TDD).

依据: https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
评审目标: app/scail2_app.py + app/static/tokens.css

每个 test 锁一条规则. 全部应当 GREEN 才算合规.
分节:
  P0  CSS-00x   anti-pattern: transition: all
  P1  TYPE-001  typography: ASCII "..." -> unicode "…"
  P1  IMG/VID    media HTML: width/height/loading (CLS)
  P2  FOCUS-001  focus states: :focus -> :focus-visible
  P2  DARK-001   color-scheme: dark on :root
  P3  TOUCH/FORM touch-action / tap-highlight / autocomplete
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app

TOKENS_CSS_PATH = REPO_ROOT / "app" / "static" / "tokens.css"
SCAIL2_APP_PATH = REPO_ROOT / "app" / "scail2_app.py"


def _tokens_css() -> str:
    return TOKENS_CSS_PATH.read_text(encoding="utf-8")


def _scail2_app_src() -> str:
    return SCAIL2_APP_PATH.read_text(encoding="utf-8")


# ============================================================
# P0  CSS-001/002/003  transition: all 反模式
# ============================================================

def test_tokens_css_has_no_transition_all():
    """规则: 'Never `transition: all`—list properties explicitly'.

    全文件 scan, 任何 'transition: all' (含 !important) 都失败.
    合理替代: 列具体属性 'transition: background ..., border-color ..., color ...'.
    注: 跳过 CSS 注释行 (/* ... */) — 注释里引用规则名是允许的.
    """
    css = _tokens_css()
    offenders = []
    for i, line in enumerate(css.splitlines(), 1):
        stripped = line.strip()
        # 跳过注释行 (单行 /* ... */ 整行注释, 或 * 子行)
        if stripped.startswith("/*") or stripped.startswith("*"):
            continue
        if re.search(r"transition\s*:\s*all\b", line):
            offenders.append(f"  L{i}: {stripped}")
    assert not offenders, (
        f"tokens.css 含 {len(offenders)} 处 'transition: all' 反模式, "
        f"应改成具体属性列表:\n" + "\n".join(offenders)
    )


def _line_numbers_for(text: str, pattern: str) -> str:
    """辅助: 返回 pattern 在 text 各行的行号列表 (用于失败信息)."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(pattern, line):
            out.append(f"  L{i}: {line.strip()}")
    return "\n".join(out) if out else "  (no match)"


# ============================================================
# P1  TYPE-001  ASCII '...' -> unicode '…' in loading states
# ============================================================

# 这些是 ComfyUI 跑流期间的 yield / progress 文案, 严格属于 "loading states".
# 排除: 注释行 (以 # 开头, 含 '...' 的英文注释 / docstring 解释) 不算违规.
# 注意: 不能用 (?<![.\w]) — Python 3 re 默认 unicode, \w 匹配中文字符,
# 会把 '准备中...' 错误排除 (因 '中' 算 \w). 用更窄的 (?<![.]) 只排除 '....' 四连点.
_ASCII_ELLIPSIS_PATTERN = re.compile(
    r'(?<![.])\.\.\.(?![.])'  # 恰好三个点, 前后不接点 (排除 '....' 四连)
)


def test_no_ascii_ellipsis_in_yield_or_progress_strings():
    """规则: 'Loading states end with `…`'.

    只扫 loading-state 语境: progress(_, desc=...) 和 yield "<status>", ...
    (Gradio 运行流文案). 不扫 docstring / 注释 / 错误消息字面量 (非 loading state).
    Unicode '…' (U+2026) 才是规范. 三连点常出现在:
      - progress(_, desc="上传参考图...")
      - yield "⏳ [1/5] uploading reference image..."
      - yield "[READY] preparing image gen..."
    """
    src = _scail2_app_src()
    offenders = []
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        # 只看 loading-state 入口: progress(...desc=...) 和 yield "...", ...
        is_progress_desc = "desc=" in line and "..." in line
        is_yield_status = re.match(r"\s*yield\s+", line) is not None
        if not (is_progress_desc or is_yield_status):
            continue
        if _ASCII_ELLIPSIS_PATTERN.search(line):
            offenders.append(f"  L{i}: {stripped}")
    assert not offenders, (
        f"scail2_app.py 含 {len(offenders)} 处 loading-state ASCII '...' (应改 Unicode '…'):\n"
        + "\n".join(offenders)
    )


# ============================================================
# P1  IMG-001/002  <img> width/height + loading=lazy
# ============================================================

def test_media_to_html_single_image_has_width_height():
    """规则: '<img> needs explicit width and height (prevents CLS)'."""
    out = scail2_app._media_to_html("http://x/y.png", output_kind="image")
    assert "<img" in out
    assert "width=" in out, f"<img> 缺 width 属性 (CLS): {out!r}"
    assert "height=" in out, f"<img> 缺 height 属性 (CLS): {out!r}"


def test_media_to_html_single_image_has_loading_lazy():
    """规则: 'Below-fold images: loading="lazy"'.

    生成结果图一般在 below-fold, 应当懒加载避免首屏抢资源.
    """
    out = scail2_app._media_to_html("http://x/y.png", output_kind="image")
    assert 'loading="lazy"' in out, f"<img> 缺 loading=lazy: {out!r}"


def test_media_to_html_image_list_grid_has_width_height():
    """网格模式每张 <img> 都要有 width/height (CLS 适用于每张)."""
    urls = ["http://x/1.png", "http://x/2.png", "http://x/3.png"]
    out = scail2_app._media_to_html(urls, output_kind="image")
    # 数 <img> 标签数 vs width= 出现次数
    n_imgs = out.count("<img ")
    n_widths = out.count("width=")
    n_heights = out.count("height=")
    n_lazy = out.count('loading="lazy"')
    assert n_imgs >= 3
    assert n_widths == n_imgs, f"网格 {n_imgs} 张图, 只有 {n_widths} 个 width=, {out!r}"
    assert n_heights == n_imgs, f"网格 {n_imgs} 张图, 只有 {n_heights} 个 height=, {out!r}"
    assert n_lazy == n_imgs, f"网格 {n_imgs} 张图, 只有 {n_lazy} 个 loading=lazy, {out!r}"


def test_media_to_html_image_in_video_context_has_dims():
    """output_kind=video 但 URL 是图扩展名 -> <img> 也要有 width/height (规则不分 context)."""
    out = scail2_app._media_to_html("http://x/a.png", output_kind="video")
    assert "<img" in out
    assert "width=" in out and "height=" in out
    assert 'loading="lazy"' in out


# ============================================================
# P1  VID-001  <video> width/height
# ============================================================

def test_media_to_html_video_has_width_height():
    """规则: <video> 也属于 embed, 需 width/height 防 CLS."""
    out = scail2_app._media_to_html("http://x/clip.mp4", output_kind="video")
    assert "<video" in out
    assert "width=" in out, f"<video> 缺 width: {out!r}"
    assert "height=" in out, f"<video> 缺 height: {out!r}"


def test_media_to_html_video_has_preload_metadata():
    """规则隐含: 视频不应默认 preload=auto 拉全文件. metadata 已足够 (规则性能条款)."""
    out = scail2_app._media_to_html("http://x/clip.mp4", output_kind="video")
    assert "<video" in out
    assert "preload=" in out, f"<video> 缺 preload 策略: {out!r}"


# ============================================================
# P2  FOCUS-001  :focus -> :focus-visible
# ============================================================

def test_input_focus_rules_use_focus_visible():
    """规则: 'Use `:focus-visible` over `:focus` (avoid focus ring on click)'.

    tokens.css 里 input/textarea 的 :focus 规则应改用 :focus-visible.
    其他元素 (如 .file-dropzone:focus-within) 用 focus-within 是合规的, 不动.
    """
    css = _tokens_css()
    # 找 'input[type="text"]:focus,' 或 'textarea:focus {' 这类
    # 但允许 :focus-within / :focus-visible
    bad = []
    for i, line in enumerate(css.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        # 跳过注释行 (注释里引用规则名 ':focus' 是允许的)
        if stripped.startswith("/*") or stripped.startswith("*"):
            continue
        # 命中 ':focus' 但既不是 ':focus-visible' 也不是 ':focus-within'
        for m in re.finditer(r":focus\b(?![-\w])", line):
            # 排除 focus-visible / focus-within
            ctx = line[m.start():m.start() + 20]
            if ctx.startswith(":focus-visible") or ctx.startswith(":focus-within"):
                continue
            bad.append(f"  L{i}: {stripped}")
            break
    assert not bad, (
        f"tokens.css 含 {len(bad)} 处裸 ':focus' (应改 ':focus-visible'):\n"
        + "\n".join(bad)
    )


# ============================================================
# P2  DARK-001  color-scheme: dark on :root
# ============================================================

def test_tokens_css_declares_color_scheme_dark():
    """规则: 'color-scheme: dark on <html> for dark themes (fixes scrollbar, inputs)'.

    tokens.css :root 块应当声明 color-scheme: dark.
    这让浏览器原生控件 (scrollbar / select / date picker) 走暗色 variant.
    """
    css = _tokens_css()
    assert "color-scheme" in css, (
        "tokens.css 缺 'color-scheme' 声明 — 暗主题下原生 scrollbar/input 会闪白"
    )
    # 进一步检查 :root 块内有 color-scheme: dark (或包含 dark)
    root_block = _extract_first_block(css, ":root {")
    assert root_block is not None
    assert re.search(r"color-scheme\s*:\s*.*dark", root_block), (
        f":root 块内未找到 'color-scheme: ...dark', 块内容片段:\n{root_block[:400]}"
    )


def _extract_first_block(text: str, opener: str) -> str | None:
    """提取首个 'opener { ... }' 块 body, 处理嵌套."""
    idx = text.find(opener)
    if idx < 0:
        return None
    start = idx + len(opener)
    depth = 1
    i = start
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


# ============================================================
# P3  TOUCH-001/002  touch-action / tap-highlight
# ============================================================

def test_tokens_css_sets_touch_action_manipulation():
    """规则: 'touch-action: manipulation (prevents double-tap zoom delay)'.

    应当设在 body 或 button/label 这类可点元素上.
    """
    css = _tokens_css()
    assert "touch-action" in css, (
        "tokens.css 缺 'touch-action' 声明 — 移动端有 300ms 双击延迟"
    )
    assert "manipulation" in css, "touch-action 应包含 'manipulation' 值"


def test_tokens_css_sets_tap_highlight_color():
    """规则: '-webkit-tap-highlight-color set intentionally'.

    默认 Android 会显示一个蓝色 / 灰色 tap highlight, 暗色主题下应当显式 transparent 或匹配主题.
    """
    css = _tokens_css()
    assert "-webkit-tap-highlight-color" in css, (
        "tokens.css 缺 '-webkit-tap-highlight-color' 声明 — 移动端点击会有默认蓝色高亮"
    )


# ============================================================
# P3  FORM-001  autocomplete on settings URL input
# ============================================================

def test_settings_url_input_has_autocomplete_off():
    """规则: 'autocomplete="off" on non-auth fields to avoid password manager triggers'.

    settings tab 的 ComfyUI URL 输入框常被浏览器误识别为登录字段, 触发密码管理器弹窗.
    显式 autocomplete="off" 关闭.

    注: Gradio 6.20 的 Textbox 没有 top-level `autocomplete` 参数, 通过
    `html_attributes={"autocomplete": "off"}` 透传到 <input>.
    """
    import gradio as gr

    url_inputs = []
    with gr.Blocks() as demo:
        scail2_app._build_settings_tab()
    for blk in demo.blocks.values():
        if isinstance(blk, gr.Textbox):
            label = (getattr(blk, "label", "") or "")
            if "地址" in label or "URL" in label.lower() or "ComfyUI" in label:
                url_inputs.append(blk)
    assert url_inputs, "未找到 ComfyUI URL Textbox — 测试需要更新"
    for inp in url_inputs:
        attrs = getattr(inp, "html_attributes", None) or {}
        ac = attrs.get("autocomplete")
        assert ac == "off", (
            f"URL Textbox (label={inp.label!r}) html_attributes['autocomplete'] 应为 'off', "
            f"实际 html_attributes={attrs!r}"
        )


# ============================================================
# Round 2 — 上一轮 "不在范围" 里现在能 TDD 推进的项
# ============================================================
#
# 重新调研结论:
#   ✅ theme-color meta    — Gradio 6 launch(head=...) 支持, 引入 _build_launch_head() helper
#   ✅ safe-area-inset     — CSS 层, 可以单元锁规则存在
#   ❌ overscroll-behavior — 项目无 modal/drawer/sheet (grep gr.Modal|gr.Dialog 全空), N/A
#   ❌ Intl.*              — history tab 已被移除 (scail2_app.py:1656 注释确认),
#                            UI 无时间戳显示, N/A


# ------------------------------------------------------------
# R2-META-001  <meta name="theme-color"> via _build_launch_head()
# ------------------------------------------------------------

def test_build_launch_head_helper_exists():
    """规则: '<meta name="theme-color"> matches page background'.

    Gradio 6 的 launch(head=...) 把字符串塞进 <head>, 我们用 _build_launch_head()
    helper 生成这段 HTML (对称于已有的 _build_launch_css()).
    """
    assert hasattr(scail2_app, "_build_launch_head"), (
        "scail2_app 应有 _build_launch_head() helper (对称 _build_launch_css), "
        "用于生成注入 <head> 的 <meta> 标签"
    )


def test_build_launch_head_contains_theme_color_meta():
    """规则: '<meta name="theme-color"> matches page background'.

    theme-color 应当匹配 --bg-app (#0f1115) — 这是浏览器 UI (地址栏 / status bar)
    着色, 跟页面背景一致才不会有"上下颜色断层".
    """
    head = scail2_app._build_launch_head()
    assert isinstance(head, str) and head, "_build_launch_head() 必须返回非空 str"
    # 必须有 <meta name="theme-color" content="#...">
    assert re.search(r'<meta\s+name=["\']theme-color["\']\s+content=["\']#([0-9a-fA-F]{3,8})["\']', head), (
        f"_build_launch_head() 缺 <meta name='theme-color' content='#...'> 标签:\n{head!r}"
    )


def test_build_launch_head_theme_color_matches_bg_app_token():
    """规则强调 'matches page background'.

    theme-color 应当与 tokens.css 里 --bg-app 的值一致 (避免地址栏跟页面有色差).
    tokens.css: --bg-app: #0f1115;
    """
    head = scail2_app._build_launch_head()
    css = _tokens_css()
    # 抽 --bg-app 的值
    m = re.search(r"--bg-app:\s*(#[0-9a-fA-F]{3,8})", css)
    assert m, "tokens.css 缺 --bg-app 定义"
    bg_app = m.group(1).lower()
    m2 = re.search(
        r'<meta\s+name=["\']theme-color["\']\s+content=["\'](#([0-9a-fA-F]{3,8}))["\']',
        head,
    )
    assert m2, f"_build_launch_head 缺 theme-color meta: {head!r}"
    theme_color = m2.group(1).lower()
    assert theme_color == bg_app, (
        f"theme-color ({theme_color}) 与 --bg-app ({bg_app}) 不一致 — "
        f"会让浏览器地址栏跟页面有色差"
    )


def test_build_launch_head_includes_color_scheme_meta():
    """规则: 'color-scheme: dark on <html> for dark themes'.

    除了 tokens.css :root { color-scheme: dark }, 还应当通过 <meta name="color-scheme">
    在 HTML 层声明一次 — 让浏览器在 CSS 加载前就知道用 dark variant (避免 FOUC).
    """
    head = scail2_app._build_launch_head()
    assert re.search(
        r'<meta\s+name=["\']color-scheme["\']\s+content=["\'].*dark.*["\']', head
    ), f"_build_launch_head 缺 <meta name='color-scheme' content='dark'>:\n{head!r}"


def test_launch_call_uses_head_param():
    """规则要求最终真的注入到 <head>.

    校验 main() / launch() 调用传了 head=_build_launch_head().
    直接读源码 — 因为 launch() 需要起 server, 没法直接 inspect 参数.
    """
    src = _scail2_app_src()
    # 找 demo.launch( ... head= ... )
    launch_block_match = re.search(
        r"demo\.launch\((.*?)\)", src, re.S
    )
    assert launch_block_match, "未找到 demo.launch(...) 调用"
    launch_block = launch_block_match.group(1)
    assert "head=" in launch_block, (
        f"demo.launch() 未传 head= 参数, theme-color meta 不会注入到 <head>.\n"
        f"launch block:\n{launch_block[:300]}"
    )


# ------------------------------------------------------------
# R2-SAFE-001  env(safe-area-inset-*) on layout containers
# ------------------------------------------------------------

def test_tokens_css_uses_safe_area_inset():
    """规则: 'Full-bleed layouts need env(safe-area-inset-*) for notches'.

    项目是 full-bleed (max-width 1700px + 水平 padding), 在 notch / island 手机
    (iPhone 14 Pro Dynamic Island, Android punch-hole) 上内容会被遮. 必须用
    env(safe-area-inset-*) 在 body 或 .gradio-container 上加内边距.
    """
    css = _tokens_css()
    assert "env(safe-area-inset" in css, (
        "tokens.css 缺 env(safe-area-inset-*) — notch / Dynamic Island 设备上"
        "内容会被状态栏 / 灵动岛遮挡"
    )


def test_safe_area_applied_to_outermost_container():
    """规则: safe-area 应当加在最外层 full-bleed 容器 (body / .gradio-container).

    不能加在内层卡片 — 内层卡片自己有父 padding, 再叠 safe-area 会双重缩进.
    """
    css = _tokens_css()
    # 找 'env(safe-area-inset' 所在的 selector 上下文 (向上找最近的 selector)
    lines = css.splitlines()
    safe_area_uses = []
    for i, line in enumerate(lines):
        if "env(safe-area-inset" not in line:
            continue
        # 向上找最近的 selector 行 (含 { 的非空非注释行)
        selector = None
        for j in range(i - 1, max(-1, i - 30), -1):
            prev = lines[j].strip()
            if not prev or prev.startswith("/*") or prev.startswith("*") or prev.startswith("//"):
                continue
            if "{" in prev:
                selector = prev
                break
        safe_area_uses.append((i + 1, selector, line.strip()))
    # 必须至少有一处用 safe-area
    assert safe_area_uses, "tokens.css 完全没用 env(safe-area-inset-*) — 见 test_tokens_css_uses_safe_area_inset"
    offenders_in_wrong_scope = []
    for ln, selector, line in safe_area_uses:
        # 合规 selector: body, html, .gradio-container (最外层)
        is_outermost = bool(selector) and any(
            s in (selector or "") for s in ("body", "html", ".gradio-container", ":root")
        )
        if not is_outermost:
            offenders_in_wrong_scope.append(
                f"  L{ln} selector={selector!r}\n     {line}"
            )
    assert not offenders_in_wrong_scope, (
        "safe-area-inset 应当只加在最外层容器 (body / html / .gradio-container), "
        "发现加在内层的:\n" + "\n".join(offenders_in_wrong_scope)
    )
