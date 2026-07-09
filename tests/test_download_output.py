"""_download_output_to_local 测试：把 ComfyUI /view URL 下载成本地文件喂给 gr.Video。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app, scail2_client


def test_download_output_to_local_returns_local_path(tmp_path):
    """下载成功 → 返回本地文件路径（在 CWD/temp 下，gr.Video 能播放）。"""
    fake_video_bytes = b"\x00\x00\x00 ftypisom\x00..."
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = fake_video_bytes
    mock_resp.iter_content = lambda *a, **k: [fake_video_bytes]
    with patch.object(scail2_client.requests, "get", return_value=mock_resp):
        local = scail2_app._download_output_to_local("http://127.0.0.1:8188/view?filename=x.mp4&subfolder=S")
    assert local is not None
    p = Path(local)
    assert p.exists()
    assert p.read_bytes() == fake_video_bytes
    # 文件名应保留原扩展名（.mp4）让 gr.Video 识别类型
    assert p.suffix == ".mp4"


def test_download_output_to_local_failure_returns_none():
    """下载失败 → 返回 None（不崩，让上层显示状态文字）。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch.object(scail2_client.requests, "get", return_value=mock_resp):
        local = scail2_app._download_output_to_local("http://127.0.0.1:8188/view?filename=missing.mp4")
    assert local is None


def test_download_output_to_local_connection_error_returns_none():
    import requests as real_req
    with patch.object(scail2_client.requests, "get", side_effect=real_req.ConnectionError("refused")):
        local = scail2_app._download_output_to_local("http://127.0.0.1:8188/view?filename=x.mp4")
    assert local is None


def test_download_output_preserves_extension():
    """不同扩展名（mp4/gif/png）都保留，让 Gradio 识别 MIME。"""
    for ext, mime_prefix in [(".mp4", b"video"), (".gif", b"GIF"), (".png", b"\x89PNG")]:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = mime_prefix + b"123"
        with patch.object(scail2_client.requests, "get", return_value=mock_resp):
            local = scail2_app._download_output_to_local(f"http://x/view?filename=out{ext}")
        assert local is not None
        assert Path(local).suffix == ext
        Path(local).unlink(missing_ok=True)
