"""布局紧致: 头部/导航有上限, 服务状态出现后仍居中, 工作流核心是统一框。"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "app-flask.css").read_text(encoding="utf-8")


def test_header_and_nav_have_max_width():
    assert ".app-shell-header {" in CSS
    body = CSS.split(".app-shell-header {", 1)[1].split("}", 1)[0]
    assert "max-width" in body
    assert ".main-tabs {" in CSS
    body = CSS.split(".main-tabs {", 1)[1].split("}", 1)[0]
    assert "max-width" in body


def test_header_and_nav_with_status_pill_on_right():
    # review 2026-07-28 (再修): 改成 grid 三列布局, 1fr 1fr 两侧等宽 spacer + auto nav 中间列 + grid-column: 3 / justify-self: end status.
    # flex 版的 margin-left: auto 不再适用 (会跟 grid 互相打架).
    assert ".main-tabs-status {" in CSS
    status_body = CSS.split(".main-tabs-status {", 1)[1].split("}", 1)[0]
    assert "grid-column: 3" in status_body, "status pill 锁 grid 第 3 列"
    assert "justify-self: end" in status_body, "status pill 在第 3 列内右对齐"
    # main-tabs 整体走 grid, 三列 1fr auto 1fr 自动等宽 spacer, nav 自然居中
    main_tabs_body = CSS.split(".main-tabs {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: 1fr auto 1fr" in main_tabs_body, "main-tabs 走 grid 三列布局"
def test_workflow_core_inside_unified_panel():
    run_html = (ROOT / "app" / "templates" / "run.html").read_text(encoding="utf-8")
    # 工作流主体包在 creator-card + form + result 区, 全部属于同一 panel
    assert "creator-card" in run_html
    assert "preset-body" in run_html
    assert "preset-result" in run_html
    # creator-card 与 preset-form / preset-result 应同包在一个 panel
    assert "preset-panel" in run_html


def test_header_nav_use_page_frame_centering():
    # header/nav 也应在 page-frame 中, 共享统一 max-width
    # base.html: header / nav 与 main 平级, 但 CSS 应给它们 max-width + 居中
    body = CSS.split(".app-shell-header {", 1)[1].split("}", 1)[0]
    assert "max-width" in body
    assert "margin: 0 auto" in body or ("margin-left: auto" in body and "margin-right: auto" in body)
    body2 = CSS.split(".main-tabs {", 1)[1].split("}", 1)[0]
    assert "max-width" in body2
    assert "margin: 0 auto" in body2 or ("margin-left: auto" in body2 and "margin-right: auto" in body2)

