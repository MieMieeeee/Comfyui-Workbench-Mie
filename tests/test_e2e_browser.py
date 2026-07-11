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

    expected = ["运行", "历史记录", "系统设置", "SCAIL2", "文生图", "开始运行"]
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
