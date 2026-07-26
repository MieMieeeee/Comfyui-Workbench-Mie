"""Creator 卡片的浏览器渲染验证 (e2e)"""
import pytest
pytestmark = pytest.mark.e2e

from playwright.sync_api import sync_playwright


def test_creator_card_renders_and_animates():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            for w, h in [(1280, 900), (390, 844)]:
                ctx = b.new_context(viewport={"width": w, "height": h}, reduced_motion="no-preference")
                page = ctx.new_page()
                page.goto("http://127.0.0.1:8199/", wait_until="domcontentloaded")
                page.wait_for_timeout(900)
                page.locator("label").filter(has_text="Anima").click()
                page.wait_for_timeout(700)
                data = page.evaluate("""() => {
                    const card = document.querySelector('[data-preset="Anima_turbo"] .creator-card');
                    if (!card) return {error: 'no card'};
                    const pfp = card.querySelector('.creator-pfp');
                    const stag = Array.from(card.querySelectorAll('.creator-stagger'));
                    return {
                        pfp: pfp && pfp.textContent.trim(),
                        pfp_bg: pfp && getComputedStyle(pfp).backgroundImage,
                        title: card.querySelector('.creator-title') && card.querySelector('.creator-title').textContent.trim(),
                        handle: card.querySelector('.creator-handle') && card.querySelector('.creator-handle').textContent.trim(),
                        bio: card.querySelector('.creator-bio') && card.querySelector('.creator-bio').textContent.trim(),
                        stagger: stag.length,
                        card_bg: getComputedStyle(card).backgroundImage,
                        theme: document.body.dataset.theme,
                    };
                }""")
                print(w, data)
                page.screenshot(path=f"F:/ComfyUIWebToRunWorkflow/_ui_shots/creator-{w}.png", full_page=True)
                ctx.close()
            ctx = b.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
            page = ctx.new_page()
            page.goto("http://127.0.0.1:8199/", wait_until="domcontentloaded")
            page.wait_for_timeout(900)
            page.locator("label").filter(has_text="Anima").click()
            page.wait_for_timeout(400)
            anims = page.evaluate("""() => Array.from(document.querySelectorAll('[data-preset="Anima_turbo"] .creator-stagger')).map(e => getComputedStyle(e).animationName)""")
            print('reduced', anims)
        finally:
            b.close()