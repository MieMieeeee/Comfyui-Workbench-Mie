"""主题 + launch CSS 注入 (Flask 版).

职责: 加载 tokens.css + 主题 JSON, 给 Flask 模板提供 CSS 字符串.
持久化: 用户选的主题写到 THEME_SETTINGS_FILE, 下次启动沿用 (coral-orange 兜底).

公开 API (flask_app.py 用):
  - _load_saved_theme() / _save_theme(tid)
  - _apply_theme(tid) -> "<style>:root{...}</style>"
  - _strip_style_tag(html)  剥 <style> 标签, 让 CSS 能直接 inject
  - _list_themes() / _get_theme_desc(tid)
  - _PAGE_BG_COLOR  模板 <meta name="theme-color"> 用

依赖: app.config.REPO_ROOT / THEME_SETTINGS_FILE
"""
from __future__ import annotations

import json
import re

from app import config

_TOKENS_CACHE: str | None = None  # deprecated: 保留符号仅为向后兼容 (旧测试会赋 None), 不再被读取
_THEMES_CACHE: list[dict] | None = None  # deprecated: 同上
_DEFAULT_THEME_ID = "forest-island"  # fallback only —— actual startup value comes from _load_saved_theme()
_THEMES_PATH = config.REPO_ROOT / "app" / "presets" / "themes.json"
_TOKENS_PATH = config.REPO_ROOT / "app" / "static" / "tokens.css"

# Page background. 必须与 tokens.css 的 --bg-app 同步 —— 浏览器 UI (地址栏 /
# status bar) 的 theme-color 跟页面背景不一致会出现"上下颜色断层". 改背景时两处一起改.
_PAGE_BG_COLOR = "#0f1115"


def _load_tokens_css() -> str:
    """读 app/static/tokens.css. 文件不存在返回空串 (不崩).

    不缓存: tokens.css 是冷资产 (页面加载时浏览器自己也会请求一次), 每次直读开销
    可忽略; 缓存反而让开发期改文件必须重启 Flask 才生效. 旧 _TOKENS_CACHE 符号保留
    仅为向后兼容 (老代码 / 测试可能赋值), 但本函数不再读它.
    """
    try:
        return _TOKENS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _list_themes() -> list[dict]:
    """读 app/presets/themes.json,返回 [{id, name, desc, tokens}, ...] 列表.

    不缓存 (同 _load_tokens_css 理由): 让开发期改 themes.json 立即生效, 且测试用
    monkeypatch._THEMES_PATH 切临时文件时不会被 stale 缓存污染.
    """
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
    return out


def _load_saved_theme() -> str:
    """启动时读取 config.THEME_SETTINGS_FILE 取上次选的主题。

    文件不存在 / 解析失败 / theme id 不在 themes.json 里 → 回退 _DEFAULT_THEME_ID(forest-island)。
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

    未知 theme_id 回落到默认主题 (forest-island),不抛异常。
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


def _theme_page_bg_color(theme_id: str) -> str:
    """返回主题自己的应用背景色，供浏览器 theme-color 使用。"""
    themes = {t["id"]: t for t in _list_themes()}
    selected = themes.get(theme_id) or themes.get(_DEFAULT_THEME_ID)
    if not selected:
        return _PAGE_BG_COLOR
    return selected["tokens"].get("--bg-app", _PAGE_BG_COLOR)


def _strip_style_tag(html: str) -> str:
    """把 "<style>...</style>" 里的 CSS 内容剥出来。无标签时原样返回。"""
    m = re.match(r"\s*<style[^>]*>(.*)</style>\s*$", html, re.S)
    return m.group(1) if m else html


def _get_theme_desc(tid: str) -> str:
    """按 theme_id 返回一行 markdown 描述。设置 tab 用。"""
    for t in _list_themes():
        if t["id"] == tid:
            return f"**{t['name']}** —— {t['desc']}"
    return ""
