"""system-bar 状态语言: “检测中”不是“加载中”.

原文 "加载中" 让用户以为有东西还在起来 (例如首次加载脚本),
实际上不是加载脚本 (脚本已经加载完), 只是在检测 ComfyUI 连接.
上报“检测中”更符合语义。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")


def test_system_status_uses_checking_zh():
    """appShell.systemStatusHtml 空值提示不是 “连接状态加载中”, 而是 “检测中”。"""
    assert "检测 ComfyUI 状态中" in APP_JS, (

        "appShell.systemStatusHtml 空值提示应使用 “检测中”, 不是“加载中” —— 脚本已加载, 只是在检测 ComfyUI 连接"
    )
    assert "连接状态加载中" not in APP_JS, "不要再用“加载中”这个误导用语"
