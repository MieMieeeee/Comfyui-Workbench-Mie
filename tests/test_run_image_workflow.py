"""run_image_workflow 文生图生成器的测试（mock client，不碰网络）。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app


def _fake_image_history(filename="z_00001_.png"):
    return {"outputs": {"9": {"images": [
        {"filename": filename, "subfolder": "", "type": "output"}
    ]}}}


def _collect(gen):
    msgs, urls = [], []
    for s, u in gen:
        msgs.append(s)
        urls.append(u)
    return msgs, urls


@pytest.fixture
def patched_image_client():
    """mock 文生图所需的 client 调用。"""
    queue_count = {"n": 0}
    def fake_queue(wf, client_id=None):
        queue_count["n"] += 1
        return f"pid-image-{queue_count['n']}"

    def fake_wait(pid, **kw):
        return iter([f"✅ done ({pid})"])

    with patch.object(scail2_app.scail2_client, "load_workflow_template") as mock_load, \
         patch.object(scail2_app.scail2_client, "queue_prompt", side_effect=fake_queue), \
         patch.object(scail2_app.scail2_client, "wait_for_completion", side_effect=fake_wait), \
         patch.object(scail2_app.scail2_client, "get_history", return_value=_fake_image_history()), \
         patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=[{"filename": "z_00001_.png", "subfolder": "", "type": "output"}]), \
         patch.object(scail2_app.scail2_client, "get_output_url",
                      side_effect=lambda f, s="", k="output": f"http://fake/view?f={f}"):
        # load 一个真实最小 zimage 结构给 patch_workflow 用
        mock_load.return_value = {
            "6": {"inputs": {"text": "x"}, "class_type": "CLIPTextEncode"},
            "13": {"inputs": {"width": 1024, "height": 1024, "batch_size": 1}, "class_type": "EmptySD3LatentImage"},
            "3": {"inputs": {"seed": 0}, "class_type": "KSampler"},
            "9": {"inputs": {}, "class_type": "SaveImage"},
        }
        yield queue_count


def test_run_image_workflow_exists():
    assert hasattr(scail2_app, "run_image_workflow")


def test_run_image_workflow_single_size(patched_image_client):
    """单尺寸：queue 1 次，yield 至少一个含 image url 的状态。

    输出格式是 Gallery 兼容：每个 yield 第二项是 url 列表（已完成的图）。
    """
    queue_count = patched_image_client
    msgs, urls = _collect(scail2_app.run_image_workflow(
        "zimage", "a photorealistic portrait", ["1024x1024"], 0
    ))
    assert queue_count["n"] == 1
    # 最后应有非空的 url 列表（Gallery value）
    assert any(isinstance(u, list) and len(u) > 0 and "view" in u[0] for u in urls)


def test_run_image_workflow_multi_size_queues_multiple(patched_image_client):
    """多尺寸：每个尺寸 queue 一次。"""
    queue_count = patched_image_client
    msgs, urls = _collect(scail2_app.run_image_workflow(
        "zimage", "a portrait", ["1024x1024", "1280x720", "720x1280"], 0
    ))
    assert queue_count["n"] == 3


def test_run_image_workflow_records_manifest(patched_image_client, tmp_path):
    """manifest 记录 preset=zimage 且有 outputs。"""
    written = []
    with patch.object(scail2_app.history, "write_manifest", side_effect=lambda m: written.append(m)):
        _collect(scail2_app.run_image_workflow("zimage", "portrait", ["1024x1024"], 42))
    assert len(written) == 1
    assert written[0]["preset"] == "zimage"
    assert written[0]["status"] == "success"


def test_run_image_workflow_fixed_seed(patched_image_client):
    """seed>0 时固定种子：每个尺寸用同一个 seed。"""
    queue_count = patched_image_client
    captured_seeds = []
    orig_patch = scail2_app.scail2_client.patch_workflow
    def spy_patch(wf, repl, **kw):
        if "3" in repl:
            captured_seeds.append(repl["3"].get("seed"))
        return orig_patch(wf, repl, **kw)
    with patch.object(scail2_app.scail2_client, "patch_workflow", side_effect=spy_patch):
        # int_random: 4th value=Checkbox state (False=固定), 5th value=Number
        _collect(scail2_app.run_image_workflow("zimage", "p", ["1024x1024", "1280x720"], False, 12345))
    # 固定 seed → 所有尺寸 seed 都是 12345
    assert all(s == 12345 for s in captured_seeds)
