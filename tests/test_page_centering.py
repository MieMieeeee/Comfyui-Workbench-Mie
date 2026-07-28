"""页面级居中: 头部、导航、主区统一水平居中。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "app-flask.css").read_text(encoding="utf-8")


def test_main_uses_centered_page_layout():
    assert "page-frame" in BASE


def test_app_header_and_nav_are_centered():
    assert ".app-shell-header" in CSS
    assert ".app-shell-header {" in CSS
    assert "text-align: center" in CSS
    head = CSS.split(".main-tabs {", 1)[1].split("}", 1)[0]
    # review 2026-07-28: nav 居中改用 grid 三列 (1fr auto 1fr), nav 锁列 2.
    # flex 的 justify-content: center 不再适用, grid 已经保证 nav 在中间列.
    assert "grid-template-columns: 1fr auto 1fr" in head, "main-tabs 应走 grid 三列布局"


def test_page_frame_centering_css():
    body = CSS.split(".page-frame {", 1)[1].split("}", 1)[0]
    assert "max-width" in body
    assert "margin: 0 auto" in body
    assert "display: flex" in body
    assert "flex-direction: column" in body


def test_settings_page_section_uses_left_text():
    # 设置页表单/输入需要左对齐, 不应继承 page-frame 居中
    assert ".settings-section {" in CSS
    body = CSS.split(".settings-section {", 1)[1].split("}", 1)[0]
    assert "text-align: left" in body or "text-align: center" not in body

