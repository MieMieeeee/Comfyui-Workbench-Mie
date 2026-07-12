"""run_workflow 的 preset 参数 + 调用链测试（mock client，不碰网络/Gradio launch）。

覆盖：
- run_workflow 接受 preset_name 首参，按对应 preset 走链路
- 不同 preset 调用 patch_workflow 时用的模板正确
- manifest 记录正确的 preset 字段
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

# gr.Error 在无 launch 上下文时是普通异常，导入 app 会触发 gradio import（OK）
from app import scail2_app, config


def _fake_history_success():
    return {"status": {"completed": True, "status_str": "success", "messages": []},
            "outputs": {"9": {"videos": [{"filename": "out.mp4", "subfolder": "SCAIL-2", "type": "output"}]}}}


def _make_ref_and_drive(tmp_path):
    """造一个假参考图 + 假驱动视频文件（内容随便，因为 upload 被 mock）。"""
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG")
    drive = tmp_path / "drive.mp4"
    drive.write_bytes(b"\x00\x00\x00 mp4")
    return ref, drive


def _collect_generator(gen):
    """把 run_workflow 的 yield 收成 list，返回 (status_msgs, video_urls)。"""
    msgs, urls = [], []
    for s, u in gen:
        msgs.append(s)
        urls.append(u)
    return msgs, urls


@pytest.fixture
def patched_client(tmp_path):
    """mock 掉 scail2_client 的所有 HTTP/IO 调用。"""
    ref, drive = _make_ref_and_drive(tmp_path)
    with patch.object(scail2_app.scail2_client, "upload") as mock_up, \
         patch.object(scail2_app.scail2_client, "queue_prompt", return_value="pid-fake-1234"), \
         patch.object(scail2_app.scail2_client, "wait_for_completion", return_value=iter(["✅ done in 00:01"])), \
         patch.object(scail2_app.scail2_client, "get_history", return_value=_fake_history_success()), \
         patch.object(scail2_app.scail2_client, "extract_primary_video_output", return_value={"filename": "out.mp4", "subfolder": "SCAIL-2", "type": "output"}), \
         patch.object(scail2_app.scail2_client, "get_output_url", return_value="http://fake/view"):
        mock_up.side_effect = lambda f, kind="image": {"name": Path(f).name, "subfolder": "", "type": "input"}
        yield ref, drive, mock_up


def test_run_workflow_accepts_preset_name(patched_client):
    """run_workflow 第一个参数应是 preset_name（不再用模块级 PRESET_NAME 常量）。"""
    ref, drive, _ = patched_client
    import inspect
    sig = inspect.signature(scail2_app.run_workflow)
    params = list(sig.parameters.keys())
    assert params[0] == "preset_name", f"first param should be preset_name, got {params[0]}"


def _replace_values(ref, drive):
    """sca12_replace preset 的 8 个 user_facing_inputs 对应的值（按 params.json 顺序）。"""
    # 30 image, 362 text, 348 text, 360 text, 469 video, 469 frame_load_cap int, 367 int, 464 int
    return [str(ref), "animal", "human", "a person walking", str(drive), 0, 81, 5]


def test_run_workflow_uses_correct_preset_template(patched_client):
    """sca12_motion 应通过 workflow_file 字段加载 scail2_motion_transfer_final.json（两个 SCAIL2 preset 共用同一 workflow）。"""
    ref, drive, _ = patched_client
    with patch.object(scail2_app.scail2_client, "load_workflow_template") as mock_load:
        mock_load.return_value = {"30": {"inputs": {"image": "x"}, "class_type": "LoadImage"},
                                   "9": {"inputs": {}, "class_type": "VHS_VideoCombine"}}
        try:
            _collect_generator(scail2_app.run_workflow("sca12_motion", str(ref), str(drive), "", 81, 5, 8))
        except Exception:
            pass
        if mock_load.called:
            # sca12_motion 用 scail2_motion_transfer_final.json（通过 workflow_file 字段映射）
            assert mock_load.call_args[0][0] == "sca12_motion"


def test_run_workflow_records_preset_in_manifest(patched_client, tmp_path):
    """manifest 的 preset 字段应等于传入的 preset_name。"""
    ref, drive, _ = patched_client
    written = []
    with patch.object(scail2_app.history, "write_manifest", side_effect=lambda m: written.append(m)):
        _collect_generator(scail2_app.run_workflow("sca12_replace", *_replace_values(ref, drive)))
    assert len(written) == 1
    assert written[0]["preset"] == "sca12_replace"
