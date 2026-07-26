"""森系小岛主题的数据、可读性与浏览器集成契约。"""
import json
from pathlib import Path

from app.services import theme
from tests.test_tokens_css_text_faint_contrast import wcag_contrast


ROOT = Path(__file__).resolve().parent.parent
THEMES = json.loads((ROOT / "app" / "presets" / "themes.json").read_text(encoding="utf-8"))


def test_forest_island_theme_has_complete_semantic_tokens():
    tokens = THEMES["forest-island"]["tokens"]
    required = {
        "--theme-id", "--theme-accent-400", "--theme-accent-500",
        "--bg-app", "--bg-panel", "--bg-card", "--bg-card-hover",
        "--bg-overlay", "--bg-input", "--border-subtle",
        "--border-default", "--border-strong", "--text-primary",
        "--text-secondary", "--text-muted", "--text-faint",
        "--text-on-accent", "--color-info", "--color-warning",
    }
    assert required <= tokens.keys()


def test_forest_island_text_contrast_is_readable():
    tokens = THEMES["forest-island"]["tokens"]
    assert wcag_contrast(tokens["--text-primary"], tokens["--bg-app"]) >= 7
    assert wcag_contrast(tokens["--text-secondary"], tokens["--bg-card"]) >= 4.5
    assert wcag_contrast(tokens["--text-faint"], tokens["--bg-card"]) >= 3.8
    assert wcag_contrast(tokens["--text-on-accent"], tokens["--theme-accent-400"]) >= 4.5


def test_theme_page_background_comes_from_selected_theme():
    assert theme._theme_page_bg_color("forest-island") == THEMES["forest-island"]["tokens"]["--bg-app"]


def test_theme_switch_updates_browser_theme_color_contract():
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "data.page_bg_color" in app_js
    assert 'meta[name="theme-color"]' in app_js
    assert "document.body.dataset.theme" in app_js


def test_theme_injector_loads_after_default_stylesheets():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert base.index("app-flask.css") < base.index('id="theme-injector"')


def test_workbench_collapses_to_single_column_on_mobile():
    css = (ROOT / "app" / "static" / "app-flask.css").read_text(encoding="utf-8")
    assert "@media (max-width: 760px)" in css
    assert ".workflow-workbench" in css
    assert "flex-direction: column" in css
    assert ".preset-body" in css


def test_forest_island_is_default_and_first_theme():
    assert theme._DEFAULT_THEME_ID == "forest-island"
    assert next(iter(THEMES)) == "forest-island"


def test_seed_random_toggle_stays_on_one_line():
    css = (ROOT / "app" / "static" / "app-flask.css").read_text(encoding="utf-8")
    assert ".int-random-field > label" in css
    assert "white-space: nowrap" in css
    assert ".int-random-field > input[type=\"number\"]" in css
    assert "min-width: 0" in css
