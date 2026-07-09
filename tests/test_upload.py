"""upload() 的纯逻辑测试（mock requests.post，不碰网络）。

覆盖：
- kind="image" 与 kind="file" 行为完全一致（当前 ComfyUI 只有一个 upload 端点）
- 缺文件抛 FileNotFoundError
- 响应缺 name 字段抛 ProtocolError_
- 非 200 抛 ProtocolError_
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_client


def _make_tmp_file(tmp_path: Path, name: str = "ref.png", content: bytes = b"\x89PNG fake") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def _mock_resp(status=200, body=None):
    r = MagicMock()
    r.status_code = status
    r.text = json.dumps(body) if body else ""
    r.json = MagicMock(return_value=body or {})
    return r


def test_kind_image_and_file_hit_same_endpoint(tmp_path):
    """kind='image' 和 kind='file' 应该 POST 到同一个 URL（当前 ComfyUI 只有 /upload/image）。"""
    f = _make_tmp_file(tmp_path, "ref.png")
    body = {"name": "ref.png", "subfolder": "", "type": "input"}

    captured_urls = []
    def fake_post(url, **kwargs):
        captured_urls.append(url)
        return _mock_resp(200, body)

    with patch.object(scail2_client.requests, "post", side_effect=fake_post):
        scail2_client.upload(f, kind="image")
        scail2_client.upload(f, kind="file")

    assert len(captured_urls) == 2
    assert captured_urls[0] == captured_urls[1]  # 同一个端点
    assert "/upload/image" in captured_urls[0]


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        scail2_client.upload(tmp_path / "nope.png")


def test_response_missing_name_raises(tmp_path):
    f = _make_tmp_file(tmp_path)
    with patch.object(scail2_client.requests, "post", return_value=_mock_resp(200, {"no_name": True})):
        with pytest.raises(scail2_client.ProtocolError_, match="missing 'name'"):
            scail2_client.upload(f)


def test_non_200_raises(tmp_path):
    f = _make_tmp_file(tmp_path)
    with patch.object(scail2_client.requests, "post", return_value=_mock_resp(400, {"error": "bad"})):
        with pytest.raises(scail2_client.ProtocolError_, match="HTTP 400"):
            scail2_client.upload(f)


def test_returns_name_subfolder_type(tmp_path):
    f = _make_tmp_file(tmp_path, "halfbody.png")
    body = {"name": "halfbody.png", "subfolder": "", "type": "input"}
    with patch.object(scail2_client.requests, "post", return_value=_mock_resp(200, body)):
        result = scail2_client.upload(f)
    assert result == body
