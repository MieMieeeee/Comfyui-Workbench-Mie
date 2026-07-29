import pytest
from playwright.sync_api import sync_playwright
pytestmark = pytest.mark.e2e


def test_page_centering_layout():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            for w in [1280, 390]:
                ctx = b.new_context(viewport={"width": w, "height": 900})
                page = ctx.new_page()
                page.goto("http://127.0.0.1:8199/", wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                run = page.evaluate("""() => {
                    const h = document.querySelector('.app-shell-header');
                    const n = document.querySelector('.main-tabs');
                    const f = document.querySelector('.page-frame');
                    const wf = document.querySelector('.workflow-workbench');
                    const items = Array.from(document.querySelectorAll('.main-tabs a, .main-tabs .nav-status'));
                    const r = el => el ? {x: Math.round(el.getBoundingClientRect().left), w: Math.round(el.getBoundingClientRect().width), cx: Math.round(el.getBoundingClientRect().left + el.getBoundingClientRect().width / 2)} : null;
                    return {
                        header: r(h), nav: r(n), frame: r(f), wf: r(wf),
                        navItems: items.map(a => ({text: a.textContent.trim(), x: Math.round(a.getBoundingClientRect().left)}))
                    };
                }""")
                print("run", w, run)
                page.screenshot(path=f"<REPO>/_ui_shots/centered-run-{w}.png", full_page=True)
                page.goto("http://127.0.0.1:8199/settings", wait_until="domcontentloaded")
                try:
                    page.wait_for_selector(".theme-options label", timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(500)
                settings = page.evaluate("""() => {
                    const f = document.querySelector('.page-frame');
                    const sp = document.querySelector('.settings-page');
                    const sec = document.querySelector('.settings-section');
                    const r = el => el ? {x: Math.round(el.getBoundingClientRect().left), w: Math.round(el.getBoundingClientRect().width), cx: Math.round(el.getBoundingClientRect().left + el.getBoundingClientRect().width / 2)} : null;
                    return {frame: r(f), settings: r(sp), section: r(sec)};
                }""")
                print("settings", w, settings)
                page.screenshot(path=f"<REPO>/_ui_shots/centered-settings-{w}.png", full_page=True)
                ctx.close()
        finally:
            b.close()
