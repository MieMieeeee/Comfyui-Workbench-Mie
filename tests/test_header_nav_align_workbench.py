"""header / nav / page-frame / workflow-workbench 在桌面视口下应共享同一 x 和 width.

避免 page-frame 多塞一层水平 padding 导致 workbench 比 header/nav 内缩 16px,
那样视觉上看起来上面比下面宽.
"""
import pytest
from playwright.sync_api import sync_playwright
pytestmark = pytest.mark.e2e


def _sizes(page):
    return page.evaluate("""() => {
        const r = (selector) => {
            const el = document.querySelector(selector);
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            return {x: Math.round(rect.x), w: Math.round(rect.width)};
        };
        return [".app-shell-header", ".main-tabs", ".page-frame", ".workflow-workbench"].map(r);
    }""")


@pytest.mark.parametrize("viewport_w", [1280, 1366, 1440, 1920])
def test_header_nav_workbench_share_same_x_and_width_at_desktop(viewport_w):
    """在桌面视口下, header / nav / page-frame / workflow-workbench 应同 x 同 width.

    之前 page-frame 额外加了 16px 水平 padding, 导致子元素比 header/nav 内缩 16px.
    这个测试锁住“子元素与 header/nav 对齐”这个契约.
    """
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            ctx = b.new_context(viewport={"width": viewport_w, "height": 800})
            page = ctx.new_page()
            page.goto("http://127.0.0.1:8199/", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            sizes = _sizes(page)
            assert sizes, "expected sizes list, got None"
            ref = sizes[0]  # header
            assert ref is not None, "header not found"
            for item in sizes[1:]:
                assert item is not None, f"element missing: {item}"
                assert item["x"] == ref["x"], (
                    f"viewport={viewport_w}: {item} x={item['x']} != header x={ref['x']}"
                )
                assert item["w"] == ref["w"], (
                    f"viewport={viewport_w}: {item} w={item['w']} != header w={ref['w']}"
                )
            ctx.close()
        finally:
            b.close()