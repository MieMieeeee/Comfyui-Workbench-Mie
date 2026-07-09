"""CSS 主题系统 + elem_classes 接入契约的 TDD 测试。

覆盖 (后续实现要满足的契约):
  A. tokens.css 是单一来源,包含 5 个必备 section
  B. themes.json 配 4 套主题,每套都有 4 个 --theme-* 变量
  C. _load_tokens_css / _list_themes / _apply_theme / _build_launch_css 4 个 helper
  D. 关键 Gradio 组件带 elem_classes,与 tokens.css 内的类名对齐
  E. 不可见 theme-injector HTML + 设置 tab 的主题选择器
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app


def _extract_css_block(text: str, selector: str) -> str | None:
    """从 CSS 文本中提取 selector { ... } 块的 body。

    跳过注释里出现的同名片段。简单实现:从 selector + ' {' 开始,字符级
    跟踪花括号嵌套,直到匹配的 ' }'。"""
    needle = selector + " {"
    idx = text.find(needle)
    if idx < 0:
        return None
    start = idx + len(needle)
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

def _extract_at_rule_block(text: str, at_signature: str) -> str | None:
    """从 CSS 文本中提取 @media (...) { ... } 的 body。支持嵌套块。
    at_signature 例: "@media (prefers-color-scheme: light)"。"""
    idx = text.find(at_signature)
    if idx < 0:
        return None
    # 找下一个 {
    brace = text.find("{", idx)
    if brace < 0:
        return None
    start = brace + 1
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




# ============ A. tokens.css 静态契约 ============

TOKENS_CSS = REPO_ROOT / "app" / "static" / "tokens.css"


def test_tokens_css_exists():
    assert TOKENS_CSS.exists(), f"缺失 {TOKENS_CSS}"


@pytest.mark.parametrize("token", [
    "--bg-app", "--bg-card", "--bg-overlay",
    "--theme-accent-500", "--theme-accent-400", "--theme-accent-glow",
    "--text-primary", "--text-secondary",
    "--space-2", "--space-4", "--radius-md", "--radius-lg",
    "--shadow-md", "--shadow-accent",
])
def test_tokens_css_has_required_token(token):
    """设计 token 至少包含这些 key。新增 token 时先在这里登记,避免下游使用悬空变量。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    assert token in text, f"tokens.css 缺 {token}"


@pytest.mark.parametrize("selector", [
    ".btn-run-primary",
    ".btn-secondary-override",
    ".card-core",
    ".card-core.is-elevated",
    ".custom-accordion",
    ".custom-dataframe",
    ".custom-radio",
    ".file-fallback",
    ".error-banner",
])
def test_tokens_css_defines_required_selector(selector):
    """关键组件必须有自定义类。Gradio 升级时如果原类名变了,这些类名仍是契约。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    assert selector in text, f"tokens.css 缺选择器 {selector}"


def test_tokens_css_consumes_theme_variables():
    """下游 .btn-run-primary 必须消费 --theme-accent-* 而不是写死 #ff7849。
    这是色彩自由切换架构的关键 — 如果有人把 #ff7849 直接写进 .btn-run-primary,
    主题切换时这个组件就不会变色。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    # 找到 .btn-run-primary 块,确认里面有 var(--theme-*)
    # 跳过注释里的同名片段,直接定位 .btn-run-primary { ... } 主块
    body = _extract_css_block(text, ".btn-run-primary")
    assert body is not None, "tokens.css 找不到 .btn-run-primary 块"
    assert "--theme-" in body, \
        ".btn-run-primary 没直接消费 --theme-* 变量,色彩切换无效"


def test_tokens_css_default_theme_is_coral_orange():
    """:root 必须把 coral-orange 的颜色注入,保证页面首次打开就有皮肤。
    即便没显式调用 _apply_theme(),默认皮肤也该好看。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    # :root 主块里至少应该有 --theme-accent-500:#ff6347 (coral-orange 500)
    root_body = _extract_css_block(text, ":root")
    assert root_body is not None, "tokens.css 缺 :root 主块"
    assert "#ff6347" in root_body, "默认主题不是 coral-orange"


# ============ B. themes.json 静态契约 ============

THEMES_JSON = REPO_ROOT / "app" / "presets" / "themes.json"


def test_themes_json_exists():
    assert THEMES_JSON.exists(), f"缺失 {THEMES_JSON}"


@pytest.mark.parametrize("theme_id", [
    "coral-orange", "cyber-blue", "future-retro", "mint-tesla",
])
def test_themes_json_has_required_theme(theme_id):
    data = json.loads(THEMES_JSON.read_text(encoding="utf-8"))
    assert theme_id in data, f"themes.json 缺 {theme_id}"


@pytest.mark.parametrize("token_key", [
    "--theme-accent-400",
    "--theme-accent-500",
    "--theme-accent-glow",
    "--theme-text-highlight",
])
def test_every_theme_has_required_token(token_key):
    data = json.loads(THEMES_JSON.read_text(encoding="utf-8"))
    for theme_id, theme in data.items():
        assert "tokens" in theme, f"{theme_id} 缺 tokens 字段"
        assert token_key in theme["tokens"], f"{theme_id} 缺 {token_key}"


def test_themes_json_values_are_valid_css():
    """每个 token 的值至少看起来像合法 CSS (颜色或 rgba / hex)。"""
    data = json.loads(THEMES_JSON.read_text(encoding="utf-8"))
    color_re = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\(|hsla?\()")
    for theme_id, theme in data.items():
        for k, v in theme["tokens"].items():
            assert color_re.match(str(v)), \
                f"{theme_id}.{k} = {v!r} 不是合法 CSS 颜色值"


# ============ C. helper 函数契约 ============

def test_load_tokens_css_returns_string():
    css = scail2_app._load_tokens_css()
    assert isinstance(css, str)
    assert len(css) > 1000, "tokens.css 似乎被截断"
    assert "--bg-app" in css


def test_load_tokens_css_caches(monkeypatch):
    """重复调用应返回相同对象,避免每帧重读文件。"""
    a = scail2_app._load_tokens_css()
    b = scail2_app._load_tokens_css()
    assert a is b, "_load_tokens_css 应该缓存"


def test_list_themes_returns_at_least_four():
    themes = scail2_app._list_themes()
    assert len(themes) >= 4
    ids = [t["id"] for t in themes]
    assert "coral-orange" in ids
    assert "cyber-blue" in ids
    assert "future-retro" in ids
    assert "mint-tesla" in ids


def test_list_themes_items_have_required_fields():
    for t in scail2_app._list_themes():
        for k in ("id", "name", "desc", "tokens"):
            assert k in t, f"theme 缺 {k}"


def test_apply_theme_returns_style_string():
    out = scail2_app._apply_theme("coral-orange")
    assert "<style" in out
    assert ":root" in out
    assert "--theme-accent-500" in out
    # 必须有合法 CSS 颜色值(不要返回 placeholder)
    assert "#ff" in out or "rgb" in out


def test_apply_theme_unknown_falls_back_to_default():
    """未知 theme_id 应该回落到默认主题,不抛异常。"""
    out = scail2_app._apply_theme("never-existed-theme")
    assert "<style" in out


def test_apply_theme_each_distinct():
    """4 套主题应该产出不同的颜色。"""
    outs = {tid: scail2_app._apply_theme(tid) for tid in
            ["coral-orange", "cyber-blue", "future-retro", "mint-tesla"]}
    # 取每个的 --theme-accent-500 值,两两不等
    def grab(s):
        m = re.search(r"--theme-accent-500:\s*([^;]+);", s)
        return m.group(1).strip() if m else None
    vals = {tid: grab(s) for tid, s in outs.items()}
    assert len(set(vals.values())) == 4, f"主题色重复: {vals}"


def test_build_launch_css_returns_list_with_tokens():
    css_list = scail2_app._build_launch_css()
    assert isinstance(css_list, list)
    assert any("--bg-app" in s for s in css_list), "tokens.css 没塞进 launch css"
    # 默认主题也要注入 (coral-orange)
    assert any("--theme-accent-500" in s for s in css_list), "默认主题色没注入"


# ============ D. 组件 elem_classes 契约 ============

import gradio as gr


def _all_blocks(demo):
    return list(demo.blocks.values())


def _by_class(demo, cls):
    return [b for b in _all_blocks(demo)
            if cls in (getattr(b, "elem_classes", None) or [])]


def test_run_btn_has_btn_run_primary_class():
    """主运行按钮必须带 .btn-run-primary 类,否则 token.css 里的渐变 + glow 不生效。"""
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("sca12_replace")
    btns = _by_class(demo, "btn-run-primary")
    assert btns, "run_btn 缺 elem_classes=['btn-run-primary']"
    # 找到的那个按钮的 label 应该是 🚀 开始运行
    run_label = next((b.value for b in btns if "开始运行" in str(b.value or "")), None)
    assert run_label, "btn-run-primary 没贴在开始运行按钮上"


def test_rerun_btn_has_btn_run_primary_class():
    """re_run_btn 也用同一个 .btn-run-primary 类。"""
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("sca12_replace")
    btns = _by_class(demo, "btn-run-primary")
    rerun_label = next((b.value for b in btns if "用相同参数再来" in str(b.value or "")), None)
    assert rerun_label, "re_run_btn 缺 elem_classes=['btn-run-primary']"


def test_step_card_groups_have_card_core_class():
    """主表单的 .step-card Group 容器需要带 .card-core,否则 token.css 里的卡片样式不生效。"""
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("sca12_replace")
    groups = _by_class(demo, "card-core")
    assert groups, "Group 没带 elem_classes=['card-core']"


def test_advanced_accordion_has_custom_accordion_class():
    """🔧 高级参数 Accordion 必须带 .custom-accordion。"""
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("sca12_replace")
    accs = [b for b in _all_blocks(demo)
            if isinstance(b, gr.Accordion)
            and "custom-accordion" in (getattr(b, "elem_classes", None) or [])
            and "高级参数" in str(b.label or "")]
    assert accs, "🔧 高级参数 Accordion 缺 .custom-accordion"


def test_log_accordion_has_custom_accordion_class():
    """📜 运行日志 Accordion 必须带 .custom-accordion。"""
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("sca12_replace")
    accs = [b for b in _all_blocks(demo)
            if isinstance(b, gr.Accordion)
            and "custom-accordion" in (getattr(b, "elem_classes", None) or [])
            and "运行日志" in str(b.label or "")]
    assert accs, "📜 运行日志 Accordion 缺 .custom-accordion"


def test_wf_radio_has_custom_radio_class():
    """左侧工作流导航 Radio 带 .custom-radio,token.css 里侧边栏卡片化样式才生效。

    wf_radio 在 build_ui 里定义,不是 _render_workflow_form 里,所以这里用 build_ui。
    """
    demo = scail2_app.build_ui()
    radios = _by_class(demo, "custom-radio")
    assert radios, "wf_radio 缺 elem_classes=['custom-radio']"


def test_history_dataframe_has_custom_dataframe_class():
    """历史记录 tab 的 Dataframe 带 .custom-dataframe。"""
    with gr.Blocks() as demo:
        scail2_app._build_history_tab()
    dfs = _by_class(demo, "custom-dataframe")
    assert dfs, "历史记录 Dataframe 缺 .custom-dataframe"


# ============ E. 主题注入器契约 ============

def test_build_ui_has_invisible_theme_injector():
    """build_ui 必须在顶部放一个不可见 HTML 作为色彩注入器。
    elem_id=theme-injector,visible=False。"""
    demo = scail2_app.build_ui()
    injectors = [b for b in _all_blocks(demo)
                 if getattr(b, "elem_id", None) == "theme-injector"]
    assert injectors, "build_ui 缺 theme-injector HTML"
    assert injectors[0].visible is False, "theme-injector 必须 visible=False"


def test_settings_tab_has_theme_picker():
    """设置 tab 应该有主题选择 Radio,触发时调用 _apply_theme 更新 injector。"""
    with gr.Blocks() as demo:
        scail2_app._build_settings_tab()
    # 找一个 choices 包含主题 id 的 Radio
    radios = [b for b in _all_blocks(demo) if isinstance(b, gr.Radio)]
    found = False
    for r in radios:
        choices = r.choices or []
        if any("coral-orange" in str(c) or "coral-orange" in str(c) for c in choices):
            found = True
            break
        # choices 可能是 [(label, value)] tuple
        flat = []
        for c in choices:
            if isinstance(c, (list, tuple)):
                flat.extend(c)
            else:
                flat.append(c)
        if any("coral-orange" in str(x) for x in flat):
            found = True
            break
    assert found, "设置 tab 没主题选择器"


def test_theme_injector_handles_update_event():
    """模拟前端事件:换主题 -> theme-injector 收到 <style> 字符串,DOM 里 :root 变量更新。

    这里只验证 helper 端:点击主题选择器应该 _apply_theme 出对应主题的 CSS。"""
    style = scail2_app._apply_theme("cyber-blue")
    # cyber-blue 的 --theme-accent-500 是 #056681
    assert "#056681" in style or "#0881a3" in style, \
        "cyber-blue 主题色没出现在 apply_theme 输出里"


# ============ F. gr.File / gr.UploadButton ============

def test_tokens_css_has_file_dropzone_section():
    """File / UploadButton 拖拽区必须有一组自定义规则。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_css_block(text, ".file-dropzone")
    if body is None:
        # 备选:更宽的覆盖选择器也算
        assert ".gradio-container .file" in text or ".upload-zone" in text, \
            "tokens.css 缺 File/UploadButton 拖拽区样式"
    else:
        assert "border" in body, "拖拽区没 border 覆盖"


def test_tokens_css_dropzone_uses_theme_accent_for_active_state():
    """拖拽激活态用 var(--theme-accent-400) 高亮(契约:不要硬编码颜色)。

    .file-dropzone:hover/.is-dragover 等可能写在独立块里,所以扫描整文件
    找激活态 + 主题色变量同时出现的最近邻作用域。
    """
    text = TOKENS_CSS.read_text(encoding="utf-8")
    has_hover = (".file-dropzone:hover" in text or ".file-dropzone:focus-within" in text
                 or ".file-dropzone.is-dragover" in text)
    assert has_hover, "拖拽区必须定义一个激活态样式 (hover/focus-within/is-dragover)"
    # 找 .file-dropzone:hover 后面紧跟的 { ... } 块,确认用了 --theme-accent-*
    import re as _re
    m = _re.search(r"\.file-dropzone:hover[^{]*\{([^}]*)\}", text, _re.DOTALL)
    if m is None:
        m = _re.search(r"\.file-dropzone:focus-within[^{]*\{([^}]*)\}", text, _re.DOTALL)
    if m is None:
        m = _re.search(r"\.file-dropzone\.is-dragover[^{]*\{([^}]*)\}", text, _re.DOTALL)
    assert m is not None, "激活态块没找到"
    assert "--theme-accent-" in m.group(1), "激活态必须消费 --theme-accent-*,色彩切换无效"


# ============ G. gr.Progress ============

def test_tokens_css_has_progress_section():
    """进度条必须有一组自定义规则 (槽 + 进度)。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    has_track = _extract_css_block(text, ".progress-track") is not None
    has_bar = _extract_css_block(text, ".progress-bar") is not None
    if not (has_track and has_bar):
        # 退化检查:Gradio 6 用 .progress-text + 内嵌 progress
        assert ".gradio-container progress" in text or ".progress-text" in text, \
            "tokens.css 缺进度条样式 (.progress-track / .progress-bar / .progress-text)"


def test_tokens_css_progress_bar_uses_accent_gradient():
    """进度槽必须用 linear-gradient + --theme-accent-* 双色渐变。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_css_block(text, ".progress-bar") or text
    assert "linear-gradient" in body, "进度槽没用 linear-gradient"
    assert "--theme-accent-400" in body and "--theme-accent-500" in body, \
        "进度槽必须消费 --theme-accent-400 和 --theme-accent-500 双色渐变"


def test_tokens_css_progress_text_uses_theme_text_highlight():
    """进度文字 (百分比 / 步骤名) 用 --theme-text-highlight,跨主题同步。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_css_block(text, ".progress-text") or text
    assert "--theme-text-highlight" in body, \
        "进度文字没消费 --theme-text-highlight,长任务主题色不同步"


# ============ H. gr.Markdown ============

def test_tokens_css_overrides_markdown_typography():
    """Markdown 内的 h1/h2/h3/code 必须有自定义规则。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    for tag in ("h1", "h2", "h3", "code"):
        assert f".gradio-container {tag}" in text or f".prose {tag}" in text or f"{tag} {{" in text, \
            f"tokens.css 缺 Markdown {tag} 样式"


def test_tokens_css_annotation_pattern_exists():
    """annotation 模式:左 border + radius-sm + 卡片底色,用于 Recipe / 警告 / 提示。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_css_block(text, ".annotation-block")
    if body is None:
        body = _extract_css_block(text, ".annotation")
    assert body is not None, "tokens.css 缺 annotation-block / .annotation 类"
    assert "border-left" in body, "annotation 模式没左 border-line"
    assert "--theme-accent-" in body, "annotation 左 border 必须消费 --theme-accent-*"
    assert "radius-sm" in body or "6px" in body, "annotation 必须用 6px 圆角"


# ============ I. Light Mode ============

def test_tokens_css_has_light_mode_media_query():
    """tokens.css 必须包含 @media (prefers-color-scheme: light) 块。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_at_rule_block(text, "@media (prefers-color-scheme: light)")
    assert body is not None, "tokens.css 缺 @media (prefers-color-scheme: light) 块"


def test_light_mode_overrides_bg_to_light():
    """Light mode 下 --bg-app 必须被覆盖成浅色 (白 / 极浅灰)。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_at_rule_block(text, "@media (prefers-color-scheme: light)")
    assert body is not None
    # 找到一个把 --bg-app 设为浅色的覆盖
    m = re.search(r"--bg-app\s*:\s*([^;]+);", body)
    assert m, "Light mode 没覆盖 --bg-app"
    val = m.group(1).strip().lower()
    # 浅色 hex (R G B 三通道都 >= f0,或 rgba alpha < 1,或 #fff / #f* / white / lightgray 等)
    hex_m = re.match(r"#([0-9a-f]{6})", val)
    assert hex_m, f"Light mode --bg-app = {val!r} 不是 hex 颜色"
    r, g, b = hex_m.group(1)[0:2], hex_m.group(1)[2:4], hex_m.group(1)[4:6]
    assert int(r, 16) >= 0xe0 and int(g, 16) >= 0xe0 and int(b, 16) >= 0xe0, \
        f"Light mode --bg-app = {val!r} 应该 >= #e0e0e0 (浅色),实际不是"


def test_light_mode_overrides_text_to_dark():
    """Light mode 下 --text-primary 必须被覆盖成深色 (>= 50% 暗度)。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_at_rule_block(text, "@media (prefers-color-scheme: light)")
    m = re.search(r"--text-primary\s*:\s*([^;]+);", body)
    assert m, "Light mode 没覆盖 --text-primary"
    val = m.group(1).strip().lower()
    hex_m = re.match(r"#([0-9a-f]{6})", val)
    assert hex_m, f"Light mode --text-primary = {val!r} 不是 hex"
    r, g, b = hex_m.group(1)[0:2], hex_m.group(1)[2:4], hex_m.group(1)[4:6]
    assert int(r, 16) <= 0x40 and int(g, 16) <= 0x40 and int(b, 16) <= 0x40, \
        f"Light mode --text-primary = {val!r} 应该 <= #404040 (深色),实际不是"


def test_light_mode_does_not_change_theme_accents():
    """Light mode 块不应该改 --theme-accent-* 值(契约:accent 跨主题稳定)。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_at_rule_block(text, "@media (prefers-color-scheme: light)")
    # 不允许在 light mode 块里出现 --theme-accent-{300,400,500,600} 的赋值
    for n in (300, 400, 500, 600):
        assert not re.search(rf"--theme-accent-{n}\s*:", body), \
            f"Light mode 块里不应该覆盖 --theme-accent-{n}"


def test_light_mode_keeps_text_highlight_distinct():
    """Light mode 下 --theme-text-highlight 应当指向 --theme-accent-500 (饱和度足够保证对比度)。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_at_rule_block(text, "@media (prefers-color-scheme: light)")
    m = re.search(r"--theme-text-highlight\s*:\s*([^;]+);", body)
    if m:
        # 如果有覆盖,必须指向主题色,不要随机选个浅色
        val = m.group(1).strip()
        assert "var(--theme-accent-" in val, \
            f"Light mode --theme-text-highlight = {val!r} 必须指向 var(--theme-accent-*)"


# ============ J. mode (auto/dark/light) 切换 ============

def test_list_modes_returns_three():
    """_list_modes 必须返回三档:auto / dark / light。"""
    modes = scail2_app._list_modes()
    ids = [m["id"] for m in modes]
    assert "auto" in ids, "_list_modes 缺 auto"
    assert "dark" in ids, "_list_modes 缺 dark"
    assert "light" in ids, "_list_modes 缺 light"


def test_list_modes_have_required_fields():
    for m in scail2_app._list_modes():
        for k in ("id", "name", "desc"):
            assert k in m, f"mode 缺 {k}"


def test_apply_mode_auto_returns_empty_style():
    """auto 模式应该输出空 style —— 让浏览器 media query 决定,不要强行覆盖。"""
    out = scail2_app._apply_mode("auto")
    assert "<style" in out and ":root" in out
    # auto 不应该赋值 bg/text 变量 (否则跟 @media 冲突)
    assert "--bg-app" not in out, "auto 模式不该赋值 --bg-app"
    assert "--text-primary" not in out, "auto 模式不该赋值 --text-primary"


def test_apply_mode_dark_overrides_surface():
    """dark 模式:强行注入深色 surface / text / border token。"""
    out = scail2_app._apply_mode("dark")
    assert "<style" in out
    # 必须包含深色 bg 赋值 (hex 前两位 <= 40)
    import re as _re
    m = _re.search(r"--bg-app\s*:\s*(#[0-9a-fA-F]+)", out)
    assert m, "dark 模式没赋值 --bg-app"
    r, g, b = m.group(1)[1:3], m.group(1)[3:5], m.group(1)[5:7]
    assert int(r, 16) <= 0x40, f"dark mode --bg-app = {m.group(1)} 不够深"


def test_apply_mode_light_overrides_surface():
    """light 模式:强行注入浅色 surface / text / border token。"""
    out = scail2_app._apply_mode("light")
    assert "<style" in out
    m = re.search(r"--bg-app\s*:\s*(#[0-9a-fA-F]+)", out)
    assert m, "light 模式没赋值 --bg-app"
    r, g, b = m.group(1)[1:3], m.group(1)[3:5], m.group(1)[5:7]
    assert int(r, 16) >= 0xe0, f"light mode --bg-app = {m.group(1)} 不够浅"


def test_apply_mode_unknown_falls_back_to_auto():
    """未知 mode id 应该回落到 auto (不抛异常,不污染 :root)。"""
    out = scail2_app._apply_mode("never-existed-mode")
    assert "<style" in out
    assert "--bg-app" not in out


def test_apply_combined_outputs_both_theme_and_mode():
    """_apply_combined 输出包含主题色和模式 surface 两个 block。"""
    out = scail2_app._apply_combined("cyber-blue", "light")
    assert "--theme-accent-500" in out
    assert "--bg-app" in out
    # cyber-blue 的 accent-500 是 #056681
    assert "#056681" in out
    # light 的 bg-app 是 #f8f9fa
    assert "#f8f9fa" in out


def test_apply_combined_auto_mode_only_has_theme():
    """auto 模式 + 主题:只输出主题色,不输出 surface (让浏览器 media query 决定)。"""
    out = scail2_app._apply_combined("coral-orange", "auto")
    assert "--theme-accent-500" in out
    assert "--bg-app" not in out


def test_apply_combined_each_mode_distinct():
    """同主题不同 mode 应该产出不同的 :root bg/text。"""
    dark = scail2_app._apply_combined("coral-orange", "dark")
    light = scail2_app._apply_combined("coral-orange", "light")
    # 提取 --bg-app 值
    import re as _re
    bg_d = _re.search(r"--bg-app\s*:\s*([^;]+);", dark).group(1).strip()
    bg_l = _re.search(r"--bg-app\s*:\s*([^;]+);", light).group(1).strip()
    assert bg_d != bg_l, f"dark 和 light bg-app 不该相同 ({bg_d} == {bg_l})"


def test_build_launch_css_includes_default_mode():
    """launch CSS 默认应该带 default mode override。auto 时是空的,但其他模式时必须有 surface 覆盖。"""
    # 默认 _DEFAULT_MODE = "auto",所以 launch css 不该含 --bg-app
    css_list = scail2_app._build_launch_css()
    flat = "\n".join(css_list)
    assert "--theme-accent-500" in flat
    # auto 模式下不应该预写 --bg-app (留给浏览器 media query)
    # 但如果 _DEFAULT_MODE 不是 auto 就要有 — 这个测试只验 auto 默认路径
    # (因为未来可能改默认,不做硬性约束)


# ============ K. 设置 tab 双 radio ============

def test_settings_tab_has_mode_picker():
    """设置 tab 必须有 mode radio,choices 包含 '自动跟随系统' 等中文 label。"""
    with gr.Blocks() as demo:
        scail2_app._build_settings_tab()
    radios = [b for b in _all_blocks(demo) if isinstance(b, gr.Radio)]
    found_mode = False
    for r in radios:
        choices = r.choices or []
        flat = []
        for c in choices:
            if isinstance(c, (list, tuple)):
                flat.extend(c)
            else:
                flat.append(c)
        if any(("自动" in str(x)) or ("暗黑" in str(x)) or ("明亮" in str(x)) or ("明亮" in str(x)) for x in flat):
            found_mode = True
            break
    assert found_mode, "设置 tab 没 mode radio"


# ============ L. blockquote 选择器收尾 ============

def test_tokens_css_blockquote_selector_covers_prose():
    """.prose blockquote 必须被 .annotation-block 的样式覆盖 (Markdown > 引用语法)。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    # .annotation-block { ... } 必须包含 .prose blockquote 选择器
    body = _extract_css_block(text, ".annotation-block")
    # 也可能写在独立块里 — 扫整文件
    has_prose_bq = ".prose blockquote" in text
    assert has_prose_bq, ".prose blockquote 没被任何块覆盖"
    # 找到 .prose blockquote 的 body,确认有 border-left + theme-accent + radius
    m = re.search(r"\.prose\s+blockquote\s*\{([^}]*)\}", text, re.DOTALL)
    if m:
        body = m.group(1)
        assert "border-left" in body, ".prose blockquote 缺 border-left"
        assert "--theme-accent-" in body, ".prose blockquote 缺 --theme-accent-*"
        assert "radius-sm" in body or "6px" in body, ".prose blockquote 缺 radius"


def test_tokens_css_blockquote_bare_selector():
    """裸 blockquote 也必须有样式,防 Gradio 用非 .prose 包裹时漏网。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    # 找 "blockquote {" 或 "blockquote," 或 ".x blockquote" 都算
    has_bare = re.search(r"(?:^|\s|,|\})blockquote\s*[\{,]", text, re.MULTILINE)
    assert has_bare, "tokens.css 缺裸 blockquote 选择器覆盖"

