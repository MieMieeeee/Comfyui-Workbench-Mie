"""截图 demo 对比页：before / after (方案 B)。

运行:
    .venv\Scripts\python.exe app\static\demo\shot.py

输出:
    app\static\demo\shot_button.png
    app\static\demo\shot_card.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent  # app/static/demo -> repo root
TARGETS = [
    ("button-compare.html", "shot_button.png"),
    ("card-compare.html", "shot_card.png"),
]


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # 1440 宽,接近常用桌面浏览器宽度
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=2)  # 2x 截图,放大镜下也不糊
        page = ctx.new_page()
        for html_name, png_name in TARGETS:
            url = (HERE / html_name).as_uri()
            page.goto(url, wait_until="networkidle")
            out = HERE / png_name
            page.screenshot(path=str(out), full_page=True)
            print(f"shot: {out.name}  ({out.stat().st_size // 1024} KB)")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())