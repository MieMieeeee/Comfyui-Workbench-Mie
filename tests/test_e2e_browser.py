"""E2E 浏览器渲染测试 —— 用真实 Chromium 加载页面,验证 SPA 能正常渲染。

这组测试锁定 2026-07-10 的页面永久"加载中"回归。那个 regression 的根因是
launch(css=list[str]) → 前端 CSSStyleSheet.replaceSync 收到 Array →
"e.replace is not a function" → Svelte 渲染崩溃。单元测试能守住 CSS 类型,
但只有真实浏览器渲染才能验证"页面真的出来了"。

默认不跑(需 --e2e): pytest --e2e tests/test_e2e_browser.py
前置: pip install -r requirements-dev.txt && playwright install chromium
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# fixture: page, gradio_server, browser 来自 conftest.py


pytestmark = pytest.mark.e2e


def test_page_renders_without_loading_stuck(page):
    """页面加载后必须渲染出真实内容,不能卡在"加载中"。

    回归锁定:regression 时 body.innerText 长度只有 6 ("加载中..."),
    SPA 框架渲染到了加载遮罩但实际内容从未出现。正常应有几百字符的 UI。
    用 networkidle 等待 + 额外缓冲,确保渲染完成。
    """
    pg, base_url = page
    pg.goto(base_url, wait_until="networkidle", timeout=20000)
    # networkidle 后再给 Svelte hydrate 一点时间
    time.sleep(2)
    body_text = pg.evaluate("document.body.innerText")
    assert len(body_text) > 100, (
        f"页面内容太少({len(body_text)} 字符),可能卡在加载中。"
        f"body 文本: {body_text!r}"
    )
    # "加载中" 不该出现在最终渲染结果里(Gradio 加载态文字)
    assert "加载中" not in body_text, "页面仍显示'加载中',SPA 渲染未完成"


def test_no_unhandled_js_errors(page):
    """页面加载期间不应有未捕获的 JS 异常。

    回归锁定:regression 时前端报 "e.replace is not a function"
    (type="module" 脚本的错误不冒泡到 window.onerror, 要专门监听 unhandledrejection)。
    """
    pg, base_url = page
    js_errors: list[str] = []
    pg.add_init_script("""
        window.__caught_errors__ = [];
        window.addEventListener('error', function(e) {
            window.__caught_errors__.push('error: ' + (e.message || String(e)));
        });
        window.addEventListener('unhandledrejection', function(e) {
            var r = e.reason;
            window.__caught_errors__.push(
                'promise: ' + (r && r.message ? r.message : String(r))
            );
        });
    """)
    pg.on("pageerror", lambda err: js_errors.append(f"pageerror: {err}"))

    pg.goto(base_url, wait_until="networkidle", timeout=20000)
    time.sleep(2)

    init_errors = pg.evaluate("window.__caught_errors__ || []")
    all_errors = js_errors + init_errors
    assert not all_errors, (
        f"页面加载期间有 {len(all_errors)} 个 JS 错误:\n"
        + "\n".join(f"  - {e}" for e in all_errors[:5])
    )


def test_no_external_network_requests(page):
    """页面加载不应发出任何指向 127.0.0.1 以外的网络请求。

    回归锁定:analytics_enabled=True 时前端会发 telemetry 到 huggingface.co,
    离线/弱网环境请求挂起拖慢 SPA。本项目必须完全本地自包含。
    放行 manifest.json 里的 github.com 示例 URL(那是组件默认值,浏览器不会主动请求)。
    """
    pg, base_url = page
    external: list[str] = []
    pg.on("request", lambda req: external.append(req.url) if _is_external(req.url, base_url) else None)

    pg.goto(base_url, wait_until="networkidle", timeout=20000)
    time.sleep(2)

    assert not external, (
        f"页面发出了 {len(external)} 个外网请求(应完全本地化):\n"
        + "\n".join(f"  - {u}" for u in external[:5])
    )


def _is_external(url: str, base_url: str) -> bool:
    """判断 url 是否指向 base_url 以外(即外网)。"""
    if not url.startswith("http"):
        return False
    # base_url 形如 http://127.0.0.1:8900
    from urllib.parse import urlparse
    base_host = urlparse(base_url).netloc
    url_host = urlparse(url).netloc
    return url_host != base_host


def test_key_ui_elements_present(page):
    """页面必须渲染出关键 UI 元素(三个 Tab + 工作流列表 + 运行按钮)。

    回归锁定:regression 时虽然 HTML 骨架返回 200,但 SPA 从未渲染出任何组件,
    所有 UI 元素都缺失。
    """
    pg, base_url = page
    pg.goto(base_url, wait_until="networkidle", timeout=20000)
    time.sleep(2)
    body_text = pg.evaluate("document.body.innerText")

    expected = ["运行", "历史记录", "系统设置", "动作迁移", "文生图", "开始运行"]
    missing = [kw for kw in expected if kw not in body_text]
    assert not missing, (
        f"页面缺少关键 UI 元素: {missing}。"
        f"body 文本({len(body_text)} 字符): {body_text[:200]!r}"
    )


def test_config_css_is_string_not_list(page):
    """Gradio /config 端点返回的 css 字段必须是 string,不能是 list/array。

    回归根因的直接验证:launch(css=list[str]) 会让前端 CSSStyleSheet.replaceSync
    收到 Array 而非 string → e.replace is not a function。
    从前端实际拿到的 config 视角守住这个类型契约。
    """
    pg, base_url = page
    pg.goto(base_url, wait_until="networkidle", timeout=20000)
    # 直接从 /config 端点拿 JSON(比从 JS 上下文读更直接)
    config_json = pg.evaluate("""async (base) => {
        const r = await fetch(base + '/config');
        return await r.json();
    }""", base_url)
    css = config_json.get("css")
    assert isinstance(css, str), (
        f"/config 的 css 字段必须是 str, 实际是 {type(css).__name__}: {css!r}"
    )
    # analytics 也该关着(E2E 视角二次确认)
    assert config_json.get("analytics_enabled") is False, \
        "analytics_enabled 应为 False(完全本地,不发 telemetry)"


def _example_basic_text_values(preset_name: str) -> list[str]:
    """Return example-backed values for visible basic text controls in spec order."""
    from app import config, scail2_app

    cfg = config.preset_config(preset_name)
    flat_values = scail2_app.example_to_form_values(preset_name)
    values = []
    flat_index = 0
    for spec in cfg["user_facing_inputs"]:
        if spec.get("tier", "basic") == "basic" and spec["type"] in ("text", "prompt_pool"):
            values.append(flat_values[flat_index])
        flat_index += 2 if spec["type"] == "int_random" else 1
    return values


def _select_preset(pg, preset_name: str) -> None:
    radio = pg.locator(f'input[type="radio"][value="{preset_name}"]').first
    radio.click()
    pg.locator(f'[id="panel-{preset_name}"]:visible').first.wait_for(timeout=5000)
    time.sleep(0.2)


def test_fresh_session_keeps_example_prompts_and_serves_versioned_previews(browser, gradio_server):
    """A prior visitor must not make a new visitor see workflow JSON defaults or stale media."""
    import hashlib
    from urllib.parse import urljoin

    from app import config

    workflows = [wf["name"] for wf in config.list_workflows()]

    # Session A visits every preset, reproducing the process-global _AUTO_LOADED pollution.
    first_context = browser.new_context(viewport={"width": 1400, "height": 900})
    first_page = first_context.new_page()
    first_page.goto(gradio_server, wait_until="networkidle", timeout=20000)
    time.sleep(1)
    for preset_name in workflows:
        _select_preset(first_page, preset_name)
    first_context.close()

    # Session B is a genuinely new browser session against the same restarted server.
    second_context = browser.new_context(viewport={"width": 1400, "height": 900})
    pg = second_context.new_page()
    pg.goto(gradio_server, wait_until="networkidle", timeout=20000)
    time.sleep(1)

    try:
        for preset_name in workflows:
            _select_preset(pg, preset_name)
            panel = pg.locator(f'[id="panel-{preset_name}"]:visible').first
            actual_texts = panel.locator("textarea:visible").evaluate_all(
                "els => els.map(el => el.value)"
            )
            expected_texts = _example_basic_text_values(preset_name)
            assert actual_texts[:len(expected_texts)] == expected_texts, (
                f"{preset_name}: fresh session prompt values differ from preset.example; "
                f"actual={actual_texts[:len(expected_texts)]!r}, expected={expected_texts!r}"
            )

            cfg = config.preset_config(preset_name)
            example = cfg["example"]
            raw = next(
                example[key]
                for key in ("preview_video", "preview_image", "preview_audio")
                if example.get(key)
            )
            preview_path = Path(raw)
            if not preview_path.is_absolute():
                preview_path = REPO_ROOT / preview_path
            expected_digest = hashlib.sha256(preview_path.read_bytes()).hexdigest()[:16]

            media = panel.locator(
                ".result-area-default source, .result-area-default img"
            ).first
            src = media.get_attribute("src")
            assert src and f"?v={expected_digest}" in src, (
                f"{preset_name}: preview src is not content-versioned; src={src!r}"
            )
            response = pg.request.get(urljoin(gradio_server + "/", src))
            assert response.ok, f"{preset_name}: preview request failed: {response.status} {src}"
            actual_digest = hashlib.sha256(response.body()).hexdigest()[:16]
            assert actual_digest == expected_digest, (
                f"{preset_name}: browser preview bytes do not match configured asset; "
                f"actual={actual_digest}, expected={expected_digest}, src={src}"
            )
    finally:
        second_context.close()
