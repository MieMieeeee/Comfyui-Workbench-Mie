"""主题 + launch CSS/head 注入 — 从 scail2_app.py 抽出的纯函数 (无 Gradio 依赖).

迁移自 scail2_app.py 的:
  - 模块常量 _TOKENS_CACHE / _THEMES_CACHE / _DEFAULT_THEME_ID /
    _THEMES_PATH / _TOKENS_PATH / _PAGE_BG_COLOR   (L1962-1966, L2090)
  - _load_tokens_css       (L1970)
  - _list_themes           (L1981)
  - _load_saved_theme      (L2001)
  - _save_theme            (L2018)
  - _apply_theme           (L2032)
  - _build_launch_css      (L2048)
  - _strip_style_tag       (L2073)
  - _get_theme_desc        (L2080)
  - _build_launch_head     (L2093)

依赖:
  - app.config.REPO_ROOT / THEME_SETTINGS_FILE

注: _build_launch_css 里有一段 Gradio 6.20.0 的 status-tracker workaround,
步骤 7 (下线 Gradio) 时这段可以删.
"""
from __future__ import annotations

import json
import re

from app import config

_TOKENS_CACHE: str | None = None
_THEMES_CACHE: list[dict] | None = None
_DEFAULT_THEME_ID = "coral-orange"  # fallback only —— actual startup value comes from _load_saved_theme()
_THEMES_PATH = config.REPO_ROOT / "app" / "presets" / "themes.json"
_TOKENS_PATH = config.REPO_ROOT / "app" / "static" / "tokens.css"

# Page background. 必须与 tokens.css 的 --bg-app 同步 —— 浏览器 UI (地址栏 /
# status bar) 的 theme-color 跟页面背景不一致会出现"上下颜色断层". 改背景时两处一起改.
_PAGE_BG_COLOR = "#0f1115"


def _load_tokens_css() -> str:
    """读 app/static/tokens.css,缓存结果。文件不存在返回空串(不崩)。"""
    global _TOKENS_CACHE
    if _TOKENS_CACHE is None:
        try:
            _TOKENS_CACHE = _TOKENS_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            _TOKENS_CACHE = ""
    return _TOKENS_CACHE


def _list_themes() -> list[dict]:
    """读 app/presets/themes.json,返回 [{id, name, desc, tokens}, ...] 列表。"""
    global _THEMES_CACHE
    if _THEMES_CACHE is None:
        try:
            raw = json.loads(_THEMES_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            raw = {}
        out: list[dict] = []
        for tid, t in raw.items():
            out.append({
                "id": tid,
                "name": t.get("name", tid),
                "desc": t.get("desc", ""),
                "tokens": t.get("tokens", {}),
            })
        _THEMES_CACHE = out
    return _THEMES_CACHE


def _load_saved_theme() -> str:
    """启动时读取 config.THEME_SETTINGS_FILE 取上次选的主题。

    文件不存在 / 解析失败 / theme id 不在 themes.json 里 → 回退 _DEFAULT_THEME_ID(coral-orange)。
    失败永不让 UI 崩,最多回到默认。
    """
    try:
        data = json.loads(config.THEME_SETTINGS_FILE.read_text(encoding="utf-8"))
        tid = data.get("theme_id")
        if tid and tid in {t["id"] for t in _list_themes()}:
            return tid
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return _DEFAULT_THEME_ID


def _save_theme(theme_id: str) -> None:
    """用户切换主题时把 theme_id 写到 config.THEME_SETTINGS_FILE 持久化。

    写盘失败(e.g. 权限)只静默 —— UI 已经看到新主题,持久化失败下次启动会回到默认。
    """
    try:
        config.THEME_SETTINGS_FILE.write_text(
            json.dumps({"theme_id": theme_id}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _apply_theme(theme_id: str) -> str:
    """生成 <style>:root{...}</style> 用于主题注入。

    未知 theme_id 回落到默认主题 (coral-orange),不抛异常。
    """
    themes = {t["id"]: t for t in _list_themes()}
    theme = themes.get(theme_id) or themes.get(_DEFAULT_THEME_ID)
    if theme is None:
        # themes.json 都坏了 —— 至少返回一个空的 style 标签,不崩
        return "<style>:root{}</style>"
    decls = "\n".join(
        f"  {k}: {v};" for k, v in theme["tokens"].items()
    )
    return f"<style>:root {{\n{decls}\n}}</style>"


def _strip_style_tag(html: str) -> str:
    """把 "<style>...</style>" 里的 CSS 内容剥出来。无标签时原样返回。"""
    m = re.match(r"\s*<style[^>]*>(.*)</style>\s*$", html, re.S)
    return m.group(1) if m else html


def _build_launch_css() -> str:
    """组装 launch(css=...) 的入参。包含 tokens.css 全文 + 默认主题。

    返回**单个 CSS 字符串**(launch(css=...) 签名是 str | None, 不是 list).
    必须是纯 CSS (不带 <style> 标签), 且必须是 str 不是 list.

    [迁移 TODO 步骤 7] 下线 Gradio 后, 中间的 status-tracker workaround 段可以删.
    """
    tokens = _load_tokens_css()
    default_combined = _apply_theme(_load_saved_theme())
    # _apply_theme 返回 "<style>:root{...}</style>",剥掉 <style></style> 标签
    default_css = _strip_style_tag(default_combined)
    # Gradio 6.20.0 workaround: advanced accordion 里的 status-tracker 永远不消失,
    # 遮住真实组件 (gr.Number / gr.Slider 都有这个 bug)。强制隐藏 .custom-accordion
    # 里的 status-tracker, 让 Number 输入框 + 最小/最大值显示能看见。运行进度仍
    # 由 运行日志 文本框显示, 不影响用户感知。
    accordion_status_tracker_fix = "/* Gradio 6.20.0 workaround: hide stuck status-tracker in accordions */ .custom-accordion [data-testid='status-tracker'] { display: none !important; }"
    # 合并成单个字符串
    return f"{tokens}\n{default_css}\n{accordion_status_tracker_fix}"


def _get_theme_desc(tid: str) -> str:
    """按 theme_id 返回一行 markdown 描述。设置 tab 用。"""
    for t in _list_themes():
        if t["id"] == tid:
            return f"**{t['name']}** —— {t['desc']}"
    return ""


def _build_launch_head() -> str:
    """生成注入 <head> 的 <meta> 标签字符串 (对称 _build_launch_css).

    内容:
      1. <meta name="theme-color" content="#0f1115">
         Web Interface Guidelines §Dark Mode: theme-color 应匹配页面背景.
         浏览器据此着色移动端地址栏 / status bar / PWA 标题栏.

      2. <meta name="color-scheme" content="dark">
         HTML 层声明 (CSS 层 tokens.css :root { color-scheme: dark } 之外再加一道),
         让浏览器在 CSS 加载前就用 dark variant —— 避免 scrollbar / <select>
         在首屏一闪而过的白底 (FOUC).
    """
    return (
        f'<meta name="theme-color" content="{_PAGE_BG_COLOR}">'
        f'<meta name="color-scheme" content="dark">'
    )
