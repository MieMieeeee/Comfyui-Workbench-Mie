"""gr.Progress 真实百分比测试 (P2: 三层进度信息去重 + 真实 step %)。

覆盖：
- _extract_step_progress 从 status_msg 里抽 "12/20" step 进度
- run_workflow 的 gr.Progress 用真实 value/max (不再 _wait_p += 0.02 匀速假进度)
- 有真实 step 时进度跟随真实值, 无 step 时才回退估算

为什么：P0 已经让 wait_for_completion yield "⏳ MM:SS  KSampler 12/20" 这种消息。
P2 把这条消息里的 12/20 抽出来, 喂给 gr.Progress(value/max, ...) —— 这样顶部固定
进度条 (用户滚动后仍可见) 跟状态条一致, 长任务体感"快完了"和"刚开始"能区分。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app


# --- _extract_step_progress (纯函数) ---

def test_extract_step_progress_parses_value_max():
    """status_msg 含 "12/20" -> (12, 20)。"""
    msg = "\u23f3 00:42  running\u2026  KSampler 12/20"
    result = scail2_app._extract_step_progress(msg)
    assert result == (12, 20)


def test_extract_step_progress_no_step_returns_none():
    """status_msg 不含 step -> None (回退估算)。"""
    msg = "\u23f3 00:42  running\u2026  KSampler"
    assert scail2_app._extract_step_progress(msg) is None


def test_extract_step_progress_zero_max_returns_none():
    """max=0 是异常值 (除零风险) -> None。"""
    msg = "\u23f3 00:42  running\u2026  5/0"
    assert scail2_app._extract_step_progress(msg) is None


def test_extract_step_progress_picks_last_ratio_in_msg():
    """msg 里多个 N/M 时取最后一个 (status 里可能有 timestamp 0:42 但那不是 ratio)。
    实际: 只认形如 数字/数字 且 max>0 的 token; 时间戳是 MM:SS 用冒号不会误匹配。"""
    msg = "\u23f3 12:34  running\u2026  KSampler 8/20"
    assert scail2_app._extract_step_progress(msg) == (8, 20)


# --- run_workflow 的 gr.Progress 用真实 step % ---

def test_run_workflow_progress_uses_real_step_value(tmp_path):
    """wait_for_completion yield 含 step "5/10" -> gr.Progress 被以 ~0.5 调用
    (在 0.45~0.92 区间内, 按真实 step 映射)。

    不再是无脑 _wait_p += 0.02 累加。用 MagicMock spy gr.Progress.__call__。
    """
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"png")
    drive = tmp_path / "drive.mp4"
    drive.write_bytes(b"mp4")

    # wait_for_completion yield 一条带 step 的 running 消息, 然后 success
    def fake_wait(pid, **kw):
        yield "\u23f3 00:01  running\u2026  KSampler 5/10"
        yield "\u2705 done"

    # 构造一个最小 sca12_motion-like preset (走 run_workflow, 不是 image)
    fake_cfg = {
        "display_name": "test", "category": "video", "output_kind": "video",
        "description": "",
        "user_facing_inputs": [
            {"node_id": "30", "field": "image", "label": "ref", "type": "file:image", "tier": "basic"},
            {"node_id": "362", "field": "text", "label": "refprompt", "type": "text", "tier": "basic", "example_key": "ref_prompt"},
            {"node_id": "360", "field": "text", "label": "main", "type": "text", "tier": "basic", "example_key": "main_prompt"},
            {"node_id": "469", "field": "video", "label": "drive", "type": "file:video", "tier": "basic"},
            {"node_id": "348", "field": "text", "label": "driveprompt", "type": "text", "tier": "basic", "example_key": "drive_prompt"},
        ],
        "example": {},
    }

    progress_calls = []

    class SpyProgress:
        def __call__(self, *args, **kwargs):
            progress_calls.append((args, kwargs))

    with patch.object(scail2_app.config, "preset_config", return_value=fake_cfg), \
         patch.object(scail2_app.scail2_client, "upload", side_effect=lambda f, kind="image": {"name": Path(f).name, "subfolder": "", "type": "input"}), \
         patch.object(scail2_app.scail2_client, "load_workflow_template", return_value={"30": {"inputs": {}, "class_type": "LoadImage", "_meta": {"title": "Load Image"}}}), \
         patch.object(scail2_app.scail2_client, "patch_workflow", side_effect=lambda wf, repl, **kw: wf), \
         patch.object(scail2_app.scail2_client, "queue_prompt", return_value=("pid", "cid")), \
         patch.object(scail2_app.scail2_client, "wait_for_completion", side_effect=fake_wait), \
         patch.object(scail2_app.scail2_client, "get_history", return_value={}), \
         patch.object(scail2_app.scail2_client, "extract_primary_video_output", return_value=None), \
         patch.object(scail2_app.scail2_client, "start_progress_listener", return_value=__import__("queue").Queue()), \
         patch.object(scail2_app, "gr") as mock_gr:
        mock_gr.Progress.return_value = SpyProgress()
        mock_gr.Error = scail2_app.gr.Error
        mock_gr.update = scail2_app.gr.update
        # 位置参数顺序对应 user_facing_inputs:
        #   [30 image, 362 ref_prompt, 360 main_prompt, 469 drive_video, 348 drive_prompt]
        list(scail2_app.run_workflow("sca12_motion", str(ref), "human", "a walk", str(drive), "human"))

    # progress(value, desc=...) 调用: args[0] 是 value 浮点, kwargs['desc'] 是描述
    values = [args[0] for args, kw in progress_calls if args]
    # 真实 step 5/10 = 0.5; 映射到 [0.45, 0.92] 区间: 0.45 + 0.5*(0.92-0.45) = 0.685
    # 关键: 不是无脑 +0.02 (=0.47 那种小增量)
    assert any(abs(v - 0.685) < 0.05 for v in values if v is not None), \
        f"expected ~0.685 (real step 5/10 mapped), got values={values}"


def test_extract_step_progress_completion_msg_ignored():
    """✅ success 消息不带 step -> None (完成态不抽 step)。"""
    msg = "\u2705 done in 00:42"
    assert scail2_app._extract_step_progress(msg) is None
