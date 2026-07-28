"""应用外壳 4 项布局打磨:
   1. .app-shell-header + .main-tabs 加 border + border-radius, 跟下面面板同一语言
   2. workflow-list label 里 emoji 和文本拆开 (上下结构, 所有项高度一致)
   3. 系统状态搬到 base.html 的 system-bar (在 main-tabs 下, 1200px 居中)
   4. creator-socials 按钮 justify-content: center
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "app" / "static" / "app-flask.css").read_text(encoding="utf-8")
BASE = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
RUN = (ROOT / "app" / "templates" / "run.html").read_text(encoding="utf-8")


def test_app_shell_header_has_border_and_radius():
    """header 加上同 .preset-panel 一样的 border + border-radius, 不是完全贯流到页边."""
    block = CSS.split(".app-shell-header {", 1)[1].split("}", 1)[0]
    assert "border:" in block
    assert "border-radius:" in block


def test_main_tabs_has_border_and_radius():
    """main-tabs 也该有 border + border-radius, 跟 header 一致."""
    block = CSS.split(".main-tabs {", 1)[1].split("}", 1)[0]
    assert "border:" in block
    assert "border-radius:" in block


def test_workflow_list_label_uses_column_layout():
    """为了 emoji 上 + 文本下的一致布局, label 起码要是 flex-direction: column."""
    block = CSS.split(".workflow-list label {", 1)[1].split("}", 1)[0]
    assert "flex-direction: column" in block, (

        ".workflow-list label 还不是 column 布局, emoji 和文本会复合在同一行"
    )
    assert "align-items: center" in block


def test_run_html_splits_icon_and_text_into_two_spans():
    """run.html 里每个项目是两个独立的 span (.wf-icon + .wf-text), 不是一个含 emoji 的长 span."""
    assert "wf-icon" in RUN and "wf-text" in RUN
    assert "w.nav_label" not in RUN, (

        "还在用 w.nav_label, 这是不一致的原因: emoji 和文本拿在一个字符串里."
    )


def test_base_html_status_pill_inside_main_tabs():
    """review 2026-07-28: ComfyUI 状态 pill (.main-tabs-status) 合并进 .main-tabs 同一行.
    少占一行垂直空间, 状态在 nav 旁边常驻可见, 不再需要独立的 .system-bar 行."""
    assert "main-tabs-status" in BASE, "main-tabs 里应有 .main-tabs-status 块"
    # 顺序: .main-tabs-status 应在 3 个 nav <a> 之后
    nav_status_idx = BASE.index("main-tabs-status")
    nav_run_idx = BASE.index(">\u25b6 \u8fd0\u884c<", 0)  # first nav link has the emoji+text
    if nav_run_idx < 0:
        # fallback: search for the nav links by attribute marker
        nav_run_idx = BASE.index("\u8fd0\u884c")
    assert nav_run_idx < nav_status_idx, "status pill 应在 nav 链接之后"
    # 不再有独立的 .system-bar 行
    assert "class=\"system-bar\"" not in BASE, "system-bar 行已并入 main-tabs, 不应再出现"


def test_run_html_no_longer_has_nav_group_system():
    """run.html 里的 .nav-group-system 被搬到 base.html 了, 不要重复."""
    assert "nav-group-system" not in RUN, (

        "还在 run.html 里留 .nav-group-system, 会在 nav-rail 下面重复出现"
    )


def test_creator_socials_is_centered():
    """.creator-socials 加了 justify-content: center, 使按钮在中间."""
    block = CSS.split(".creator-socials {", 1)[1].split("}", 1)[0]
    assert "justify-content: center" in block