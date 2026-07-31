"""WebSocket step 进度解析测试 (P0: KSampler/SamplerCustom value/max)。

覆盖：
- _parse_ws_event 解析 ComfyUI ws 事件 (progress / executing / done / unknown)
- start_progress_listener 失败时返回空队列不抛 (降级契约)
- wait_for_completion 接 progress_queue 时 yield 带 step "12/20"
- wait_for_completion 不传 progress_queue 时跟现状一致 (向后兼容)

架构: 后台 ws 线程把事件塞进 queue.Queue, 同步生成器 drain queue。
测试不开真 ws 连接 —— 全部 mock start_progress_listener 返回预填队列。
"""
from __future__ import annotations

import queue
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_client


def _collect(gen):
    return list(gen)


# --- _parse_ws_event (纯函数, 无 IO) ---

def test_ws_progress_event_parses_value_max():
    """progress 事件 -> ("progress", value, max, None)。
    KSampler/SamplerCustom 每个 step 推一条, value 1..max。"""
    msg = {"type": "progress", "data": {"value": 12, "max": 20}}
    parsed = scail2_client._parse_ws_event(msg)
    assert parsed is not None
    kind, value, mx, node_id = parsed
    assert kind == "progress"
    assert value == 12
    assert mx == 20
    assert node_id is None


def test_ws_executing_event_parses_node_id():
    """executing 事件带 node id -> ("executing", None, None, "367")。
    ComfyUI 每开始执行一个节点推一条。"""
    msg = {"type": "executing", "data": {"node": "367"}}
    parsed = scail2_client._parse_ws_event(msg)
    assert parsed is not None
    kind, value, mx, node_id = parsed
    assert kind == "executing"
    assert node_id == "367"
    assert value is None and mx is None


def test_ws_completion_event_parses():
    """executing 事件 node=None -> ("done", ...) 标志整个 prompt 完成。"""
    msg = {"type": "executing", "data": {"node": None}}
    parsed = scail2_client._parse_ws_event(msg)
    assert parsed is not None
    assert parsed[0] == "done"


def test_ws_execution_error_event_parses_prompt_and_message():
    msg = {"type": "execution_error", "data": {"prompt_id": "pid-failed", "node_id": "7", "exception_message": "CUDA error: no kernel image is available"}}
    parsed = scail2_client._parse_ws_event(msg)
    assert parsed is not None
    assert parsed[0] == "error"
    assert parsed[3] == "7"
    assert parsed[4] == "pid-failed"
    assert "no kernel image" in parsed[5]


def test_ws_unknown_event_returns_none():
    """未知事件类型 -> None (调用方跳过, 不崩)。
    ComfyUI 偶尔推 status / execution_cached 等事件, 不影响进度显示。"""
    assert scail2_client._parse_ws_event({"type": "status"}) is None
    assert scail2_client._parse_ws_event({"type": "execution_cached", "data": {"nodes": ["3"]}}) is None


def test_ws_progress_event_missing_data_returns_none():
    """progress 事件缺 data / value / max -> None (异常 ws 帧, 不崩)。"""
    assert scail2_client._parse_ws_event({"type": "progress"}) is None
    assert scail2_client._parse_ws_event({"type": "progress", "data": {}}) is None


# --- start_progress_listener (失败降级) ---

def test_start_progress_listener_returns_queue_even_on_failure(monkeypatch):
    """ws 连不上 / websockets 没装 -> 返回空队列, 不抛异常。
    降级契约 (AGENTS.md 信任模型): ComfyUI 配套整合包, 失败不堆防御,
    静默回退到轮询。"""
    # 模拟 websockets import 失败
    monkeypatch.setattr(scail2_client, "_websockets_available", False)
    q = scail2_client.start_progress_listener("client-xyz")
    assert isinstance(q, queue.Queue)
    assert q.empty()


# --- wait_for_completion 接 progress_queue ---

def test_wait_for_completion_yields_step_progress_with_title_map():
    """progress_queue 预放 progress 事件 + title_map -> yield 含 "12/20" 和 title。
    这是 P0 核心: 长任务体感质变, 不再是匀速假进度。"""
    pq = queue.Queue()
    pq.put({"type": "progress", "data": {"value": 12, "max": 20}})
    pq.put({"type": "executing", "data": {"node": "367"}})
    # history 一直未完成 -> 持续 yield running 消息 (drain queue)
    seq = [None,
           {"status": {"completed": False, "status_str": "", "messages": [["executing", "367"]]}},
           {"status": {"completed": True, "status_str": "success", "messages": []}}]
    title_map = {"367": "KSampler"}
    with patch.object(scail2_client, "get_history", side_effect=seq):
        msgs = _collect(scail2_client.wait_for_completion(
            "pid", timeout_sec=30, poll_interval_sec=0,
            title_map=title_map, progress_queue=pq,
        ))
    # 至少有一条 running 消息带 step 进度
    running_msgs = [m for m in msgs if m.startswith("\u23f3")]
    assert running_msgs, f"no running msgs in {msgs}"
    joined = " ".join(running_msgs)
    assert "12/20" in joined, f"step 12/20 missing in running msgs: {running_msgs}"
    assert "KSampler" in joined, f"title KSampler missing: {running_msgs}"


def test_wait_for_completion_degrades_when_ws_unavailable():
    """progress_queue 是空队列 (ws 连不上) -> 走现状轮询路径, 仍能成功。
    降级契约: 不传/空 queue 时行为完全等同 P1 之后、P0 之前。"""
    pq = queue.Queue()  # 永远空 (模拟 ws 连不上, listener 返回空队列)
    seq = [None,
           {"status": {"completed": True, "status_str": "success", "messages": []}}]
    with patch.object(scail2_client, "get_history", side_effect=seq):
        msgs = _collect(scail2_client.wait_for_completion(
            "pid", timeout_sec=30, poll_interval_sec=0, progress_queue=pq,
        ))
    assert msgs[-1].startswith("\u2705")  # 仍能正常完成


def test_wait_for_completion_stops_on_ws_execution_error_before_history():
    pq = queue.Queue()
    pq.put({"type": "execution_error", "data": {"prompt_id": "pid", "node_id": "7", "exception_message": "CUDA error: no kernel image is available"}})
    with patch.object(scail2_client, "get_history", return_value=None):
        msgs = _collect(scail2_client.wait_for_completion("pid", timeout_sec=30, poll_interval_sec=0, title_map={"7": "CLIPTextEncode"}, progress_queue=pq))
    assert len(msgs) == 1
    assert msgs[0].startswith("\u274c")
    assert "CLIPTextEncode" in msgs[0]
    assert "no kernel image" in msgs[0]


def test_wait_for_completion_ignores_ws_error_for_other_prompt():
    pq = queue.Queue()
    pq.put({"type": "execution_error", "data": {"prompt_id": "other-pid", "exception_message": "other run failed"}})
    hist = {"status": {"completed": True, "status_str": "success", "messages": []}}
    with patch.object(scail2_client, "get_history", return_value=hist):
        msgs = _collect(scail2_client.wait_for_completion("pid", timeout_sec=30, poll_interval_sec=0, progress_queue=pq))
    assert msgs == ["\u2705 done in 00:00"]


def test_wait_for_completion_step_progress_falls_back_when_no_queue():
    """不传 progress_queue -> 完全跟现状一致 (向后兼容锁)。
    现有 4 个调用方 / 12 个测试都依赖这个默认行为。
    running 消息不带 step "12/20" (因为没有 progress 源)。"""
    # 序列要包含一个未完成的 history 才会产生 running 消息
    seq = [None,
           {"status": {"completed": False, "status_str": "", "messages": []}},
           {"status": {"completed": True, "status_str": "success", "messages": []}}]
    with patch.object(scail2_client, "get_history", side_effect=seq):
        msgs = _collect(scail2_client.wait_for_completion(
            "pid", timeout_sec=30, poll_interval_sec=0,
        ))
    # 至少有一条 running 消息
    running_msgs = [m for m in msgs if m.startswith("\u23f3") and "running" in m]
    assert running_msgs, f"no running msgs in {msgs}"
    # running 消息不带 step "N/M" (没有 progress 源时 step_str 为空)
    for m in running_msgs:
        assert "/" not in m, f"unexpected step in fallback running msg: {m}"


def test_wait_for_completion_progress_sentinel_terminates_cleanly():
    """progress_queue 收到 None sentinel (任务结束信号) -> 不崩, 不阻塞。
    wait_for_completion 结束时调 pq.put(None) 通知 ws 线程退出, 这条锁该协议。"""
    pq = queue.Queue()
    pq.put(None)  # sentinel (模拟 wait_for_completion finally 发的退出信号)
    seq = [{"status": {"completed": True, "status_str": "success", "messages": []}}]
    with patch.object(scail2_client, "get_history", side_effect=seq):
        msgs = _collect(scail2_client.wait_for_completion(
            "pid", timeout_sec=30, poll_interval_sec=0, progress_queue=pq,
        ))
    assert msgs[-1].startswith("\u2705")


# --- queue_prompt 签名变更 ---

def test_queue_prompt_returns_prompt_id_and_client_id():
    """queue_prompt 改成返回 (prompt_id, client_id)。
    调用方拿 client_id 喂 start_progress_listener。
    不传 client_id 时自动生成 uuid (避免 concurrent run 串数据)。"""
    fake_resp = {"prompt_id": "pid-abc"}
    with patch.object(scail2_client.requests, "post") as mock_post:
        mock_post.return_value.json.return_value = fake_resp
        mock_post.return_value.status_code = 200
        result = scail2_client.queue_prompt({"3": {"class_type": "X"}})
    # 返回元组 (prompt_id, client_id)
    assert isinstance(result, tuple)
    assert len(result) == 2
    prompt_id, client_id = result
    assert prompt_id == "pid-abc"
    assert client_id  # 非空


def test_queue_prompt_uses_supplied_client_id():
    """传了 client_id -> 原样用它 (调用方控制, e.g. 复用现有 'gradio-ui')。"""
    fake_resp = {"prompt_id": "pid-def"}
    with patch.object(scail2_client.requests, "post") as mock_post:
        mock_post.return_value.json.return_value = fake_resp
        mock_post.return_value.status_code = 200
        prompt_id, client_id = scail2_client.queue_prompt(
            {"3": {"class_type": "X"}}, client_id="gradio-ui",
        )
    assert prompt_id == "pid-def"
    assert client_id == "gradio-ui"
