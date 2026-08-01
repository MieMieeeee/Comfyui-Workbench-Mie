"""theme 模块不应缓存 themes.json / tokens.css (开发期改文件需重启才生效).

Bug: _TOKENS_CACHE / _THEMES_CACHE 模块级缓存无失效机制. fix: 直接每次读文件,
冷资产读写开销可忽略, 且 _apply_theme 调用频率低. 用 monkeypatch 改文件内容验证.
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app.services import theme, theme as theme_mod


def test_list_themes_picks_up_file_change(monkeypatch, tmp_path):
    """改 themes.json 后 _list_themes 立即看到新主题 (不重启)."""
    fake_themes = tmp_path / "themes.json"
    fake_themes.write_text(json.dumps({
        "fake-theme": {
            "name": "Fake Theme",
            "desc": "test only",
            "tokens": {"--bg-app": "#000000", "--theme-accent-400": "#ff0000"},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(theme_mod, "_THEMES_PATH", fake_themes)
    themes = theme._list_themes()
    ids = [t["id"] for t in themes]
    assert "fake-theme" in ids
    fake = [t for t in themes if t["id"] == "fake-theme"][0]
    assert fake["name"] == "Fake Theme"
    assert fake["tokens"]["--bg-app"] == "#000000"


def test_load_tokens_css_picks_up_file_change(monkeypatch, tmp_path):
    """改 tokens.css 后 _load_tokens_css 立即看到新内容."""
    fake_tokens = tmp_path / "tokens.css"
    fake_tokens.write_text(":root { --fresh-token: #abcdef; }", encoding="utf-8")
    monkeypatch.setattr(theme_mod, "_TOKENS_PATH", fake_tokens)
    css = theme._load_tokens_css()
    assert "--fresh-token" in css


def test_apply_theme_uses_live_themes(monkeypatch, tmp_path):
    """_apply_theme 应从最新文件读, 不依赖启动时缓存."""
    fake_themes = tmp_path / "themes.json"
    fake_themes.write_text(json.dumps({
        "live-theme": {
            "name": "Live",
            "desc": "live",
            "tokens": {"--bg-app": "#111111"},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(theme_mod, "_THEMES_PATH", fake_themes)
    style = theme._apply_theme("live-theme")
    assert "#111111" in style
