"""scail2_client 的运行时可变 base URL + 连接检查测试。

目标：让 ComfyUI 地址运行时可改（与 config 解耦），UI 设置页能修改 + 测试连通性。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_client, config


# --- 运行时 URL 状态 ---

def test_get_base_url_default_matches_config():
    """初始 base url 应等于 config.COMFY_BASE_URL。"""
    scail2_client.reset_base_url()  # 重置到默认，避免被其他测试污染
    assert scail2_client.get_base_url() == config.COMFY_BASE_URL


def test_set_base_url_changes_get():
    scail2_client.reset_base_url()
    scail2_client.set_base_url("http://192.168.1.100:8188")
    assert scail2_client.get_base_url() == "http://192.168.1.100:8188"


def test_set_base_url_normalizes_trailing_slash():
    """带尾斜杠的 URL 应规范化（去掉尾斜杠），避免拼成 //prompt。"""
    scail2_client.set_base_url("http://127.0.0.1:8188/")
    assert scail2_client.get_base_url() == "http://127.0.0.1:8188"


def test_set_base_url_strips_whitespace():
    scail2_client.set_base_url("  http://example.com:8188  ")
    assert scail2_client.get_base_url() == "http://example.com:8188"


def test_reset_base_url_returns_to_config():
    scail2_client.set_base_url("http://other:8188")
    scail2_client.reset_base_url()
    assert scail2_client.get_base_url() == config.COMFY_BASE_URL


# --- upload 等调用应使用运行时 URL ---

def test_upload_uses_runtime_url(tmp_path):
    """upload 应打到运行时 base url（不是 config 的）。"""
    scail2_client.set_base_url("http://runtime-host:8188")
    f = tmp_path / "ref.png"
    f.write_bytes(b"\x89PNG")
    captured = []
    def fake_post(url, **kw):
        captured.append(url)
        r = MagicMock()
        r.status_code = 200
        r.json = MagicMock(return_value={"name": "ref.png", "subfolder": "", "type": "input"})
        return r
    try:
        with patch.object(scail2_client.requests, "post", side_effect=fake_post):
            scail2_client.upload(f)
        assert captured[0].startswith("http://runtime-host:8188")
    finally:
        scail2_client.reset_base_url()


def test_get_output_url_uses_runtime_url():
    scail2_client.set_base_url("http://rt:8188")
    try:
        url = scail2_client.get_output_url("x.mp4", "sub")
        assert url.startswith("http://rt:8188/view")
    finally:
        scail2_client.reset_base_url()


# --- check_connection ---

def test_check_connection_ok():
    """ComfyUI 可达时返回成功状态。"""
    scail2_client.reset_base_url()
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json = MagicMock(return_value={"system": {"os": "nt"}})
    with patch.object(scail2_client.requests, "get", return_value=ok_resp):
        ok, msg = scail2_client.check_connection()
    assert ok is True
    assert "OK" in msg or "就绪" in msg or "reachable" in msg.lower()


def test_check_connection_fail():
    """ComfyUI 不可达时返回失败状态（不抛异常）。"""
    scail2_client.set_base_url("http://nonexistent-host-12345:8188")
    try:
        ok, msg = scail2_client.check_connection(timeout=2)
        assert ok is False
        assert isinstance(msg, str) and len(msg) > 0
    finally:
        scail2_client.reset_base_url()


def test_check_connection_specific_url():
    """check_connection(url=...) 用指定 url 测试，不影响全局状态。"""
    scail2_client.reset_base_url()
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json = MagicMock(return_value={})
    with patch.object(scail2_client.requests, "get", return_value=ok_resp) as mock_get:
        scail2_client.check_connection(url="http://test-specific:8188")
        # 应请求指定 url
        assert "http://test-specific:8188" in mock_get.call_args[0][0]
    # 全局状态不变
    assert scail2_client.get_base_url() == config.COMFY_BASE_URL
