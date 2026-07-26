"""运行页三项布局契约:
   1. inputs/outputs 各占独立框 (.preset-controls / .preset-result 各自有 border + bg)
   2. 顶部两行 + workbench 同宽 (1200px 填满)
   3. idle 状态下运行状态条不可见 (避免脚你重复出现空框)
"""
import pytest
from playwright.sync_api import sync_playwright
pytestmark = pytest.mark.e2e


def _eval(page, js):
    return page.evaluate(js)


def test_inputs_and_outputs_each_have_own_frame():
    """.preset-controls 和 .preset-result 都应有自己的 border + bg, 不能关赖于 parent."""
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            ctx = b.new_context(viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            page.goto("http://127.0.0.1:8199/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            info = _eval(page, """() => {
                const c = document.querySelector('.preset-controls');
                const r = document.querySelector('.preset-result');
                const cs = el => {
                    if (!el) return null;
                    const s = getComputedStyle(el);
                    return {border: s.border, bg: s.backgroundColor};
                };
                return {controls: cs(c), result: cs(r)};
            }""")
            assert info["controls"] is not None and info["result"] is not None
            # 两边都应有 border (1px solid)
            for k in ("controls", "result"):
                assert "1px solid" in info[k]["border"], f"{k} border 丢失: {info[k]['border']}"
            # 两边都应有背景 (不是 transparent)
            for k in ("controls", "result"):
                assert "rgba(0, 0, 0, 0)" not in info[k]["bg"], f"{k} bg 丢失: {info[k]['bg']}"
            ctx.close()
        finally:
            b.close()


def test_status_bar_hidden_when_idle():
    """新 Flask/Alpine 应用 idle 不该显示运行状态条.

    之前 tokens.css 里 .run-status-bar { display: flex !important } 会覄掊 Alpine x-show 的 inline display:none.
    这个测试锁住“不能加 !important”这个契约.
    """
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            ctx = b.new_context(viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            page.goto("http://127.0.0.1:8199/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            info = _eval(page, """() => {
                const sb = document.querySelector('.run-status-bar');
                const cs = getComputedStyle(sb);
                return {display: cs.display, h: sb.getBoundingClientRect().height};
            }""")
            assert info["display"] == "none", f"status bar 仍显示 (idle 不应看到), display={info['display']}"
            assert info["h"] == 0, f"status bar height should be 0 when hidden, got {info['h']}"
            ctx.close()
        finally:
            b.close()


def test_no_legacy_display_flex_important_on_run_status_bar():
    """防范性: tokens.css 不应给 .run-status-bar 加 display: flex !important.

    只要加了, idle 状态下运行条会隐藏不了, 出现“空框在输出上面”.
    """
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / "app" / "static" / "tokens.css").read_text(encoding="utf-8")
    assert "display: flex !important" not in css.split(".run-status-bar {", 1)[1].split("}", 1)[0], (
        ".run-status-bar 里还有 display: flex !important, 会覄掊 Alpine x-show 的 inline display:none"
    )


def test_workbench_content_spans_full_max_width():
    """workflow-workbench 不应有水平 padding, 子元素 (nav + main) 要填满 1200px 跟顶部对齐."""
    css_path = "app/static/app-flask.css"
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / css_path).read_text(encoding="utf-8")
    # 提取 .workflow-workbench 块
    block = css.split(".workflow-workbench {", 1)[1].split("}", 1)[0]
    # 不能有水平 padding (不要 var(--space-X) 出现在 padding 行)
    import re
    padding_lines = [ln for ln in block.split("\n") if "padding" in ln]
    for ln in padding_lines:
        # 只允许 0 在左右, 不能有 var(--space-N) 填满左右
        left = re.search(r"padding:\s*0\s+var\(--space-\d+\)\s+var\(--space-\d+\)", ln)
        assert not left, f"workflow-workbench 仍有水平 padding: {ln}"
