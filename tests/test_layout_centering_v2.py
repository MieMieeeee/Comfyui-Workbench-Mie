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


def test_header_and_nav_center_when_nav_status_visible():
    # nav-status 用 margin-left: auto 在 flex 中被推到右边, 居中失效
    body = CSS.split(".main-tabs {", 1)[1].split("}", 1)[0]
    assert "margin-left: auto" not in body
    assert ".nav-status {" in CSS
    nav_status = CSS.split(".nav-status {", 1)[1].split("}", 1)[0]
    # nav-status 改为独立块, 整体居中后下方一行
    assert "margin-left: auto" not in nav_status or "flex-basis: 100%" in CSS


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

