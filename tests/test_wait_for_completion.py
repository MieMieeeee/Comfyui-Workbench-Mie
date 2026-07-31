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


# --- 执行异常终止 (bug fix 2026-07-31) ---
#
# 用户场景: ComfyUI 报 torch.AcceleratorError: CUDA error: no kernel image is available
# (torch 版本与 GPU 算力不兼容). ComfyUI 源码 (main.py prompt_worker) 此时把
# /history status 写成 {completed: False, status_str: 'error'}, messages 含
# execution_error 带 exception_message.
#
# 修复前 wait_for_completion 唯一终止判定是 `if completed:`, completed=False 时
# 永远走 "未完成 -> 继续 running", UI 卡在 "运行中" 直到 30 分钟超时.
# 这两条锁住: status_str == 'error' / 'failed' (容错多版本) 也必须终止并 yield ❌.
def test_execution_error_with_completed_false_terminates():
    """ComfyUI 执行异常 (torch/CUDA 崩溃) 时 status.completed=False + status_str='error'.

    必须立即 yield 一条 ❌ 并停止, 不能继续 running, 也不能走到超时.
    这是用户截图里卡死 7 分钟 bug 的直接复现.
    """
    hist = {"status": {
        "completed": False,
        "status_str": "error",
        "messages": [["execution_error", {"exception_message": "CUDA error: no kernel image is available for execution on the device", "exception_type": "torch.AcceleratorError"}]],
    }}
    with patch.object(scail2_client, "get_history", return_value=hist):
        msgs = _collect(scail2_client.wait_for_completion("pid", timeout_sec=60, poll_interval_sec=0))
    # 只 yield 一条 (终止), 不会循环 running 到超时
    assert len(msgs) == 1, f"expected single terminal msg, got {msgs}"
    assert msgs[0].startswith("\u274c"), f"expected ❌, got {msgs[0]}"
    assert "no kernel image" in msgs[0], f"原始异常信息必须透传: {msgs[0]}"


def test_status_failed_also_terminates():
    """status_str='failed' (ComfyUI 版本/方言变体) 同样必须终止.

    信任模型: 内建 workflow 不会无故返失败, 真返了就是执行端炸了, 终止比卡死强.
    """
    hist = {"status": {
        "completed": False,
        "status_str": "failed",
        "messages": [["execution_error", {"exception_message": "boom"}]],
    }}
    with patch.object(scail2_client, "get_history", return_value=hist):
        msgs = _collect(scail2_client.wait_for_completion("pid", timeout_sec=60, poll_interval_sec=0))
    assert len(msgs) == 1, f"expected single terminal msg, got {msgs}"
    assert msgs[0].startswith("\u274c")
    assert "boom" in msgs[0]
