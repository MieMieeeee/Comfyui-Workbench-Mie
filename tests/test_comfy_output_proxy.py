"""局域网客户端通过 WebUI 同源代理读取 ComfyUI 产物。"""
from unittest.mock import MagicMock, patch

import requests

from app import flask_app, history, scail2_client


def test_output_urls_are_same_origin_relative_paths():
    assert scail2_client.get_output_url("result 1.png", "album/a", "output") == (
        "/comfy_output?filename=result%201.png&type=output&subfolder=album/a"
    )
    assert history.make_view_url("clip.mp4", "videos", "temp").startswith("/comfy_output?")


def test_proxy_forwards_only_to_configured_comfy_view():
    upstream = MagicMock()
    upstream.status_code = 200
    upstream.headers = {"Content-Type": "image/png", "Content-Length": "7", "ETag": "abc"}
    upstream.iter_content.return_value = iter([b"png", b"data"])
    upstream.close = MagicMock()
    with flask_app.app.test_client() as client, patch.object(flask_app.scail2_client, "get_base_url", return_value="http://127.0.0.1:8188"), patch.object(flask_app.requests, "get", return_value=upstream) as get:
        response = client.get("/comfy_output?filename=result.png&type=output&subfolder=album")
    assert response.status_code == 200
    assert response.data == b"pngdata"
    assert response.content_type == "image/png"
    assert response.headers["Cache-Control"] == "no-store"
    get.assert_called_once_with(
        "http://127.0.0.1:8188/view",
        params={"filename": "result.png", "type": "output", "subfolder": "album"},
        stream=True, timeout=(5, 120),
    )


def test_proxy_rejects_missing_filename_and_invalid_type():
    with flask_app.app.test_client() as client:
        assert client.get("/comfy_output?type=output").status_code == 400
        assert client.get("/comfy_output?filename=x.png&type=http://evil").status_code == 400


def test_proxy_maps_connection_failure_to_502():
    with flask_app.app.test_client() as client, patch.object(flask_app.requests, "get", side_effect=requests.ConnectionError("down")):
        response = client.get("/comfy_output?filename=x.png&type=output")
    assert response.status_code == 502
