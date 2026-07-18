"""多尺寸文生图总进度测试 (P3: segment + step 合成)。

覆盖：
- run_image_workflow 的 gr.Progress 把 segment 区间 [(idx-1)/n, idx/n] 跟当前尺寸内
  step value/max 合成总进度
- 3 尺寸第 2 尺寸内 step 10/20 -> 总进度 ≈ (1 + 10/20) / 3 = 0.5

为什么：P0/P2 只解决了单尺寸的 step 进度; 多尺寸时每个尺寸占 [(idx-1)/n, idx/n]
区间, 尺寸内的 step 应该填满这个区间, 而不是 _seg_p += 0.02 匀速假进度。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app
from app import config


def _fake_image_history():
    return {"outputs": {"9": {"images": [{"filename": "z_00001_.png", "subfolder": "", "type": "output"}]}}}


def test_run_image_workflow_progress_combines_segment_and_step():
    """3 尺寸, 第 2 尺寸内 step 10/20 -> gr.Progress 总进度 ≈ 0.5。

    数学: seg2 区间 = [1/3, 2/3]; step 10/20 = 0.5;
    总进度 = seg_start + step_ratio * (seg_end - seg_start) = 1/3 + 0.5*(1/3) = 0.5。
    """
    # wait_for_completion 第 2 次调用 (第 2 尺寸) yield 带 step 的消息
    # 用 side_effect 区分每次调用: 前两次走完, 第 2 次带 step
    wait_calls = {"n": 0}
    def fake_wait(pid, **kw):
        wait_calls["n"] += 1
        if wait_calls["n"] == 2:
            yield "\u23f3 00:10  running\u2026  KSampler 10/20"
        yield "\u2705 done"

    progress_calls = []
    class SpyProgress:
        def __call__(self, *args, **kwargs):
            progress_calls.append((args, kwargs))

    with patch.object(scail2_app.scail2_client, "load_workflow_template") as mock_load, \
         patch.object(scail2_app.scail2_client, "queue_prompt",
                      side_effect=lambda wf, **kw: (f"pid-{id(wf)}", f"cid-{id(wf)}")), \
         patch.object(scail2_app.scail2_client, "wait_for_completion", side_effect=fake_wait), \
         patch.object(scail2_app.scail2_client, "get_history", return_value=_fake_image_history()), \
         patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=[{"filename": "z.png", "subfolder": "", "type": "output"}]), \
         patch.object(scail2_app.scail2_client, "get_output_url",
                      side_effect=lambda f, s="", k="output": f"http://fake/view?f={f}"), \
         patch.object(scail2_app.scail2_client, "start_progress_listener",
                      return_value=__import__("queue").Queue()), \
         patch.object(scail2_app, "gr") as mock_gr:
        mock_load.return_value = {
            "6": {"inputs": {"text": "x"}, "class_type": "CLIPTextEncode"},
            "13": {"inputs": {"width": 1024, "height": 1024, "batch_size": 1}, "class_type": "EmptySD3LatentImage"},
            "3": {"inputs": {"seed": 0}, "class_type": "KSampler"},
            "9": {"inputs": {}, "class_type": "SaveImage"},
        }
        mock_gr.Progress.return_value = SpyProgress()
        mock_gr.Error = scail2_app.gr.Error
        list(scail2_app.run_image_workflow("zimage", "a portrait", ["1024x1024", "1280x720", "720x1280"], 0))

    # 第 2 尺寸 step 10/20 时总进度应 ≈ 0.5 (= 1/3 + 0.5 * 1/3)
    values = [a[0] for a, k in progress_calls if a]
    # 找接近 0.5 的值 (容忍 0.02 误差)
    assert any(abs(v - 0.5) < 0.03 for v in values), \
        f"expected ~0.5 (seg2 + step 10/20), got values={values}"


def test_run_image_workflow_progress_each_segment_advances():
    """每个尺寸开始时进度跳到该尺寸区间起点 (seg_start), 不停留在上一尺寸末尾。
    3 尺寸: 进度应出现 ~0, ~0.333, ~0.667 这三个区间起点附近。"""
    def fake_wait(pid, **kw):
        yield "\u2705 done"

    progress_calls = []
    class SpyProgress:
        def __call__(self, *args, **kwargs):
            progress_calls.append((args, kwargs))

    with patch.object(scail2_app.scail2_client, "load_workflow_template") as mock_load, \
         patch.object(scail2_app.scail2_client, "queue_prompt",
                      side_effect=lambda wf, **kw: (f"pid-{id(wf)}", f"cid-{id(wf)}")), \
         patch.object(scail2_app.scail2_client, "wait_for_completion", side_effect=fake_wait), \
         patch.object(scail2_app.scail2_client, "get_history", return_value=_fake_image_history()), \
         patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=[{"filename": "z.png", "subfolder": "", "type": "output"}]), \
         patch.object(scail2_app.scail2_client, "get_output_url",
                      side_effect=lambda f, s="", k="output": f"http://fake/view?f={f}"), \
         patch.object(scail2_app.scail2_client, "start_progress_listener",
                      return_value=__import__("queue").Queue()), \
         patch.object(scail2_app, "gr") as mock_gr:
        mock_load.return_value = {
            "6": {"inputs": {"text": "x"}, "class_type": "CLIPTextEncode"},
            "13": {"inputs": {"width": 1024, "height": 1024, "batch_size": 1}, "class_type": "EmptySD3LatentImage"},
            "3": {"inputs": {"seed": 0}, "class_type": "KSampler"},
            "9": {"inputs": {}, "class_type": "SaveImage"},
        }
        mock_gr.Progress.return_value = SpyProgress()
        mock_gr.Error = scail2_app.gr.Error
        list(scail2_app.run_image_workflow("zimage", "a portrait", ["1024x1024", "1280x720", "720x1280"], 0))

    values = [a[0] for a, k in progress_calls if a]
    # 最终应有接近 1.0 的完成进度
    assert any(abs(v - 1.0) < 0.05 for v in values), \
        f"expected ~1.0 completion, got values={values}"
