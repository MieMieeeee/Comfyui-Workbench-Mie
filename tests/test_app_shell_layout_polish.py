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
    """为了 emoji 上 + 文本下的一致布局, label 起码要是 flex-direction: column.

    review 2026-07-29: nav 改成 .nav-group-list (review 加组概念后),
    跟 .workflow-list 走同一个 :is() 选择器, 都走 flex-direction: column.
    """
    import re
    m = re.search(r":is\(\.workflow-list,\s*\.nav-group-list\)\s+label\s*\{([^}]*)\}", CSS)
    assert m, "没找到 :is(.workflow-list, .nav-group-list) label 块"
    block = m.group(1)
    assert "flex-direction: column" in block, (
        "label 还不是 column 布局, emoji 和文本会复合在同一行"
    )
    assert "align-items: center" in block


def test_run_html_moves_icon_from_workflow_to_group_header():
    """review 2026-07-29: 图标从工作流名挪到组头 (🎬 视频 / 🖼️ 图像 这种).

    之前是每个工作流名有 .wf-icon, 现在:
    - 工作流名只有 .wf-text (没图标)
    - 组头 .nav-group-name 里多一个 .nav-group-icon span
    """
    assert "wf-icon" not in RUN, (
        "工作流名前不应再有 .wf-icon, 图标挪到组头了"
    )
    assert "wf-text" in RUN, "工作流名仍应有 .wf-text"
    assert "nav-group-icon" in RUN, "组头应有 .nav-group-icon (icon span)"
    assert "nav-group-name" in RUN, "组头应有 .nav-group-name"
    assert "w.nav_label" not in RUN, (
        "还在用 w.nav_label, 这是不一致的原因: emoji 和文本拿在一个字符串里."
    )
    js = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "groupIcons" in js, "app.js 应有 groupIcons 映射"
    for g in ("图像", "视频", "音频", "通用", "其他"):
        assert g in js, f"app.js groupIcons 应覆盖 {g}"


def test_base_html_status_pill_inside_main_tabs():
    """review 2026-07-28: ComfyUI 状态 pill (.main-tabs-status) 合并进 .main-tabs 同一行.
    少占一行垂直空间, 状态在 nav 旁边常驻可见, 不再需要独立的 .system-bar 行."""
    assert "main-tabs-status" in BASE, "main-tabs 里应有 .main-tabs-status 块"
    # 顺序: .main-tabs-status 应在 3 个 nav <a> 之后
    # review 2026-07-29: 菜单栏 '▶ 运行' -> '🎬 工作流' -> '🏠 首页' (标签跟具体内容无关, 只要是主页 tab 就行)
    # 用 url_for('index') 链接作为锚点, 不再绑死文案
    nav_run_idx = BASE.index("url_for('index')")  # 第一个 <a href="{{ url_for('index') }}"> 链接
    assert nav_run_idx >= 0, "main-tabs-nav 里应有指向 / (index) 的链接 (即首页/工作流 tab)"
    # 锚点应在 status pill 之前
    nav_status_idx = BASE.index("main-tabs-status")
    assert nav_run_idx < nav_status_idx, "首页 tab 应在 status pill 之前"
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