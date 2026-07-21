"""设置 tab 的 URL 保存/测试/恢复逻辑测试。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app, scail2_client, config


def setup_function():
    scail2_client.reset_base_url()


def test_save_and_test_url_success():
    """保存 URL 并测试连通 → 返回成功信息，且 URL 已更新。"""
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json = MagicMock(return_value={})
    with patch.object(scail2_client.requests, "get", return_value=ok_resp):
        msg = scail2_app.save_and_test_url("http://192.168.1.50:8188")
    assert scail2_client.get_base_url() == "http://192.168.1.50:8188"
    assert "就绪" in msg or "OK" in msg


def test_save_and_test_url_fail():
    """保存 URL 但连不上 → 返回失败信息，但 URL 仍更新（用户可能稍后启动 ComfyUI）。"""
    with patch.object(scail2_client, "check_connection", return_value=(False, "无法连接")):
        msg = scail2_app.save_and_test_url("http://dead-host:8188")
    assert scail2_client.get_base_url() == "http://dead-host:8188"
    assert "无法连接" in msg


def test_save_and_test_url_normalizes():
    """保存的 URL 去掉尾斜杠。"""
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json = MagicMock(return_value={})
    with patch.object(scail2_client.requests, "get", return_value=ok_resp):
        scail2_app.save_and_test_url("http://127.0.0.1:8188/")
    assert scail2_client.get_base_url() == "http://127.0.0.1:8188"


def test_reset_to_default_url():
    """恢复默认按钮 → URL 回到 config 默认值。"""
    scail2_client.set_base_url("http://custom:8188")
    new_url, msg = scail2_app.reset_to_default_url()
    assert new_url == config.COMFY_BASE_URL
    assert scail2_client.get_base_url() == config.COMFY_BASE_URL
    assert isinstance(msg, str)


def test_get_default_url():
    """获取默认 URL（给 UI 输入框的 placeholder/默认值用）。"""
    url = scail2_app.get_default_url()
    assert url == config.COMFY_BASE_URL


def test_save_empty_url_handled():
    """空 URL 不应崩溃 → 返回提示。"""
    msg = scail2_app.save_and_test_url("")
    assert isinstance(msg, str) and len(msg) > 0
