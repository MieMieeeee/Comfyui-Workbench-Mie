"""共享 pytest 配置 —— marker 注册、--e2e 开关、Gradio server fixture。

项目原本每个测试文件自己 sys.path.insert，这是第一个 conftest，提供跨文件共享的:
  - `e2e` marker 注册 + 默认跳过逻辑（不传 --e2e 就 skip）
  - `gradio_server` fixture：E2E 用，在临时空闲端口起 Gradio，测完干净关闭
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest


# ---------------------------------------------------------------------------
# marker + --e2e 开关
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="运行标记为 e2e 的浏览器渲染测试（需 playwright + chromium）",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "e2e: 需要真实浏览器（playwright），默认不跑，用 --e2e 启用",
    )


def pytest_collection_modifyitems(config, items):
    """未传 --e2e 时，把所有 e2e 测试自动 skip。

    不用 deselect（那样连计数都没有），而是 allow_module_level 风格的 skip，
    让 pytest -q 输出里能看到 "5 skipped"，明确提示有 E2E 测试存在。
    """
    if config.getoption("--e2e"):
        return
    skip_e2e = pytest.mark.skip(reason="需要 --e2e 才运行浏览器测试")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


# ---------------------------------------------------------------------------
# gradio_server fixture（E2E 用）
# ---------------------------------------------------------------------------

def _find_free_port(preferred_range=range(8900, 8920)) -> int:
    """在 preferred_range 里找一个可绑定的空闲端口。

    Gradio 的 launch(prevent_thread_lock=True) 在后台线程跑 server，
    我们用 socket 探活确认起来再 yield。
    """
    for port in preferred_range:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            s.close()
            continue
    # 回退：让操作系统分配
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    """轮询端口直到 Gradio 监听或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        if s.connect_ex((host, port)) == 0:
            s.close()
            return True
        s.close()
        time.sleep(0.3)
    return False


@pytest.fixture(scope="session")
def gradio_server(tmp_path_factory):
    """起一个临时端口的 Gradio server，返回 base_url。

    session 级：整个测试会话只起一次（Gradio 启动慢，~5s），
    所有 E2E 测试共用同一个 server 实例。

    用 prevent_thread_lock=True 让 launch 在后台跑，
    yield 后调 demo.close() 干净关闭（释放端口 + 线程）。

    NO_PROXY 设置:Gradio 6 的 launch() 在"Running on local URL"后会同步 httpx.get
    自己的 /startup-events 端点(timeout=None)。如果系统配了 HTTP 代理(本项目开发机
    有 127.0.0.1:7777 代理),这个自连接请求会走代理 → 卡死 → launch 永不返回。
    设 NO_PROXY=localhost,127.0.0.1 让 httpx 对 localhost 绕过代理。
    """
    import os

    from app import scail2_app

    # 浏览器测试不得读取或改写用户的持久化主题设置。
    e2e_data_dir = tmp_path_factory.mktemp("e2e-app-data")
    scail2_app.config.THEME_SETTINGS_FILE = e2e_data_dir / "theme_settings.json"
    scail2_app.CSS = scail2_app._build_launch_css()

    # 关键:让 Gradio 内部的 httpx 自连接绕过系统代理,否则 launch() 卡死
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"
    os.environ["no_proxy"] = "localhost,127.0.0.1"

    port = _find_free_port()
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}"

    demo = scail2_app.build_ui()
    demo.queue()
    # prevent_thread_lock=True → launch 立即返回，server 在后台线程跑。
    # launch 参数要与 main() 保持一致(css/theme/footer_links 等),否则 E2E
    # 测的是与生产不同的配置 —— 最典型就是漏传 css 会让 /config.css=None,
    # 而 regression 正是 css 类型问题,E2E 必须覆盖到它。
    demo.launch(
        server_name=host,
        server_port=port,
        prevent_thread_lock=True,
        show_error=True,
        theme=scail2_app.THEME,
        css=scail2_app.CSS,
        footer_links=[],
        enable_monitoring=False,
        allowed_paths=[scail2_app.config.REPO_ROOT / "app" / "static" / "examples"],
    )

    if not _wait_for_port(host, port, timeout=20.0):
        try:
            demo.close()
        except Exception:
            pass
        pytest.fail(f"Gradio server 没能在 {base_url} 起来（20s 超时）")

    yield base_url

    # teardown：干净关闭
    try:
        demo.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# playwright fixture（E2E 用，懒加载）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def browser():
    """playwright chromium 浏览器，session 级复用。

    懒 import：没有装 playwright 时，只有真跑 E2E 才报错，
    普通 pytest -q 不会因为 import playwright 失败。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright 未安装；pip install -r requirements-dev.txt && playwright install chromium")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox"])
        yield b
        b.close()


@pytest.fixture
def page(browser, gradio_server):
    """每个测试一个独立 page（隔离 JS 状态），共用 session 级 browser + server。

    默认导航到 gradio_server 的根页。context 新建保证 cookie/storage 隔离。
    """
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    pg = context.new_page()
    yield pg, gradio_server
    context.close()
