"""wait_for_completion 的生成器行为测试（mock get_history，不碰网络）。

覆盖：
- success 后 generator 终止（不再 yield）
- failure 后终止
- timeout 后终止
- connection error 后终止
- waiting → running → done 的正常流
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_client


def _collect(gen):
    """把 generator 收成 list。"""
    return list(gen)


def test_success_then_stops():
    """history 一开始就 completed+success → 只 yield 一个 ✅ 然后停。"""
    hist = {"status": {"completed": True, "status_str": "success", "messages": []}}
    with patch.object(scail2_client, "get_history", return_value=hist):
        msgs = _collect(scail2_client.wait_for_completion("pid", timeout_sec=10, poll_interval_sec=0))
    assert len(msgs) == 1
    assert msgs[0].startswith("\u2705")


def test_failure_then_stops():
    """completed 但 status_str != success → yield ❌ 然后停。"""
    hist = {"status": {"completed": True, "status_str": "error",
                        "messages": [["execution_error", "CUDA OOM"]]}}
    with patch.object(scail2_client, "get_history", return_value=hist):
        msgs = _collect(scail2_client.wait_for_completion("pid", timeout_sec=10, poll_interval_sec=0))
    assert len(msgs) == 1
    assert msgs[0].startswith("\u274c")
    assert "OOM" in msgs[0]


def test_connection_error_then_stops():
    """get_history 抛 ConnectionError_ → yield ❌ 然后停。"""
    def boom(_pid):
        raise scail2_client.ConnectionError_("boom")
    with patch.object(scail2_client, "get_history", side_effect=boom):
        msgs = _collect(scail2_client.wait_for_completion("pid", timeout_sec=10, poll_interval_sec=0))
    assert len(msgs) == 1
    assert "connection error" in msgs[0]


def test_waiting_then_running_then_success():
    """None → completed 的正常流转：waiting, waiting, success。"""
    seq = [None, None, {"status": {"completed": True, "status_str": "success", "messages": []}}]
    with patch.object(scail2_client, "get_history", side_effect=seq):
        msgs = _collect(scail2_client.wait_for_completion("pid", timeout_sec=30, poll_interval_sec=0))
    # 2 个 waiting + 1 个 success = 3
    assert len(msgs) == 3
    assert msgs[0].startswith("\u23f3") and "waiting" in msgs[0]
    assert msgs[1].startswith("\u23f3") and "waiting" in msgs[1]
    assert msgs[2].startswith("\u2705")


def test_timeout():
    """history 一直是 None，且 timeout 极短 → 超时 yield ⏰。"""
    with patch.object(scail2_client, "get_history", return_value=None):
        msgs = _collect(scail2_client.wait_for_completion("pid", timeout_sec=0, poll_interval_sec=0))
    # timeout_sec=0 时 while 条件立刻 false，直接 yield timeout（可能无 waiting）
    assert msgs[-1].startswith("\u23f0")
