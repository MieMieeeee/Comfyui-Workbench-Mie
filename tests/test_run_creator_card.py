"""运行页 Creator-style 卡片头：保留森系主题 + 不破坏工作台密度。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "app" / "templates" / "run.html").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "app-flask.css").read_text(encoding="utf-8")
TOKENS = (ROOT / "app" / "static" / "tokens.css").read_text(encoding="utf-8")


def test_creator_card_uses_theme_color_tokens():
    assert "creator-card" in TEMPLATE
    assert "var(--theme-accent-400)" in CSS
    assert "var(--bg-panel)" in CSS
    assert "var(--bg-card)" in CSS
    assert "creator-pfp" not in TEMPLATE
    assert "creator-pfp" not in CSS


def test_creator_card_has_handle_and_bio():
    assert "creator-handle" in TEMPLATE
    assert "creator-bio" in TEMPLATE
    assert "preset_actions" in TEMPLATE or "preset-actions" in TEMPLATE


def test_creator_card_stagger_animation_respects_reduced_motion():
    assert "@keyframes creator-rise" in CSS
    assert "prefers-reduced-motion: reduce" in CSS
    assert "creator-stagger" in CSS


def test_creator_card_uses_emoji_initial_pfp():
    assert "x-text=" in TEMPLATE
    assert "creator-pfp" not in TEMPLATE


def test_creator_card_layout_adapts_to_mobile():
    assert "@media (max-width: 640px)" in CSS


