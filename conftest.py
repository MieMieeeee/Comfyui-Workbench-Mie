"""共享 pytest 配置 —— sys.path 修正 + e2e marker 注册.

项目原本每个测试文件自己 sys.path.insert, 这是第一个 conftest, 提供跨文件共享的:
  - sys.path 修正 (让 tests/ 直接 import app.*)
  - `e2e` marker 注册 + 默认跳过逻辑 (不传 --e2e 就 skip)

历史: 原有 gradio_server / page / browser fixture (给 Gradio 版 playwright E2E 用)
在 migrate-to-flask (2026-07-21) 后已删除 —— scail2_app.py 不存在, fixture 引用
已断. Flask 版的 E2E 替代 (用 flask test client) 尚未补, 详见
tests/_archive_gradio/README.md.
"""
from __future__ import annotations

import sys
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
    让 pytest -q 输出里能看到 "N skipped"，明确提示有 E2E 测试存在。
    """
    if config.getoption("--e2e"):
        return
    skip_e2e = pytest.mark.skip(reason="需要 --e2e 才运行浏览器测试")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)
