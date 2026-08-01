"""health_check.check_health 在 url=None 时应读 scail2_client 运行时 base URL.

Bug: 之前回退到 config.COMFY_BASE_URL, 绕过用户在设置页改的运行时地址,
导致状态灯(走 scail2_client)显示绿但完整健康检查(走 health_check)探错地址.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import health_check, scail2_client, config


def _mock_resp(status=200, json_body=None):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=json_body or {})
    r.text = "body"
    return r


SYSTEM_STATS_OK = {
    "system": {"comfyui_version": "0.3.14"},
    "devices": [{"name": "NVIDIA GeForce RTX 4090", "type": "cuda",
                 "vram_total": 25769803776, "vram_free": 19565942784}],
}


def test_check_health_url_none_uses_runtime_base_url():
    """url=None 时应探 scail2_client.get_base_url() 而非 config 默认值."""
    runtime_url = "http://192.168.50.77:8188"
    # 让两者明确不同, 才能区分 health_check 探的是哪个
    assert runtime_url != config.COMFY_BASE_URL
    captured = []

    def fake_get(url, *a, **kw):
        captured.append(url)
        return _mock_resp(200, SYSTEM_STATS_OK)

    try:
        scail2_client.set_base_url(runtime_url)
        with patch.object(health_check.requests, "get", side_effect=fake_get):
            report = health_check.check_health()  # url=None
    finally:
        scail2_client.reset_base_url()

    # health_check 应该探运行时地址 (拿 system_stats 那次)
    sys_stats_hits = [u for u in captured if u.endswith("/system_stats")]
    assert sys_stats_hits, f"未发 /system_stats 请求, captured={captured}"
    assert runtime_url in sys_stats_hits[0], (
        f"应探运行时 URL {runtime_url}, 实际探了 {sys_stats_hits[0]}")


def test_check_health_explicit_url_still_wins():
    """显式传 url 时仍优先用传入值 (向后兼容)."""
    captured = []

    def fake_get(url, *a, **kw):
        captured.append(url)
        return _mock_resp(200, SYSTEM_STATS_OK)

    try:
        scail2_client.set_base_url("http://runtime-only:8188")
        with patch.object(health_check.requests, "get", side_effect=fake_get):
            health_check.check_health(url="http://explicit-host:8188")
    finally:
        scail2_client.reset_base_url()

    sys_stats_hits = [u for u in captured if u.endswith("/system_stats")]
    assert sys_stats_hits
    assert "explicit-host" in sys_stats_hits[0]
