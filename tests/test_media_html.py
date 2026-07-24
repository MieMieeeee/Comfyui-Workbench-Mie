"""`_media_to_html` / `_media_ext_from_url` 回归测试 (Flask 版).

背景: 原来的测试在 tests/_archive_gradio/test_ui_helpers.py, import scail2_app
(scail2_app.py 已在 migrate-to-flask 步骤 7 删除). 这里移植 + 锁 Flask 版契约:
  - ComfyUI /view URL 的扩展名从 filename= query 取 (不能靠 URL endswith)
  - 本地文件 URL 走 Flask 路由 (/comfy_input/ 或 /static/), 不是旧的 /gradio_api/file=
"""
from pathlib import Path

from app.services import media as media_svc


# ---------------------------------------------------------------------------
# _media_ext_from_url
# ---------------------------------------------------------------------------

def test_media_ext_comfyui_view_url_with_filename_query():
    """ComfyUI /view URL 末尾是 &subfolder=..., 不能靠 URL endswith, 要解析 query."""
    url = "http://127.0.0.1:8188/view?filename=scail-2_00094-audio.mp4&type=output&subfolder=SCAIL-2"
    assert media_svc._media_ext_from_url(url) == ".mp4"


def test_media_ext_simple_url_still_works():
    assert media_svc._media_ext_from_url("http://x/clip.mp4") == ".mp4"
    assert media_svc._media_ext_from_url("http://x/y.png") == ".png"
    assert media_svc._media_ext_from_url("http://x/clip.MOV") == ".mov"


def test_media_ext_query_param_short_f():
    """测试用 URL (?f= 而不是 ?filename=) 也要识别."""
    assert media_svc._media_ext_from_url("http://127.0.0.1:8188/view?f=clip_00001.mp4") == ".mp4"
    assert media_svc._media_ext_from_url("http://127.0.0.1:8188/view?f=z_00001_.png") == ".png"


def test_media_ext_local_path():
    assert media_svc._media_ext_from_url(r"C:/foo/bar.mp4") == ".mp4"
    assert media_svc._media_ext_from_url("/tmp/img.PNG") == ".png"


def test_media_ext_no_extension():
    assert media_svc._media_ext_from_url("http://x/view") == ""
    assert media_svc._media_ext_from_url("") == ""
    assert media_svc._media_ext_from_url(None) == ""


# ---------------------------------------------------------------------------
# _media_to_html — ComfyUI HTTP URL (主路径)
# ---------------------------------------------------------------------------

def test_media_to_html_none_returns_placeholder():
    assert "等待结果" in media_svc._media_to_html(None)


def test_media_to_html_empty_image_list_returns_placeholder():
    assert "等待结果" in media_svc._media_to_html([], output_kind="image")


def test_media_to_html_single_image_url():
    out = media_svc._media_to_html("http://x/y.png", output_kind="image")
    assert "<img" in out and "http://x/y.png" in out


def test_media_to_html_image_list_grid():
    out = media_svc._media_to_html(
        ["http://x/a.png", "http://x/b.png"], output_kind="image"
    )
    assert out.count("<img") == 2


def test_media_to_html_comfyui_view_url_renders_video_tag():
    """ComfyUI /view URL 在 video context 渲染成 <video>, 不是'未知输出格式' banner."""
    url = "http://127.0.0.1:8188/view?filename=scail-2_00094-audio.mp4&type=output&subfolder=SCAIL-2"
    out = media_svc._media_to_html(url, output_kind="video")
    assert "<video" in out
    assert "controls" in out
    assert "未知输出格式" not in out


def test_media_to_html_image_extension_video_context_still_image():
    """video context 但 URL 是图片扩展名 -> 渲染 <img> (跨类型不死锁)."""
    out = media_svc._media_to_html("http://x/y.png", output_kind="video")
    assert "<img" in out


def test_media_to_html_unknown_http_url_falls_back_to_video_banner():
    """未知扩展名 http URL + video context -> 走 video 兜底 banner (提供下载).

    output_kind 是 hint: URL 扩展名无法识别时, 按 output_kind 给最可能的兜底.
    """
    out = media_svc._media_to_html("http://x/file.xyz", output_kind="video")
    # http URL 原样可用 -> video 兜底 banner 提供下载链接
    assert "file-fallback" in out
    assert "http://x/file.xyz" in out


# ---------------------------------------------------------------------------
# _media_to_html — 本地文件 → Flask 路由 (新, 锁迁移契约)
# ---------------------------------------------------------------------------

def test_media_to_html_local_comfy_input_file_uses_comfy_input_route(tmp_path, monkeypatch):
    """COMFY_INPUT_DIR 下的本地文件 -> /comfy_input/<basename>.

    原来是 /gradio_api/file=<绝对路径>, Flask 版没这条路由, 改用 /comfy_input/.
    """
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    f = input_dir / "thumb.png"
    f.write_bytes(b"x")
    monkeypatch.setattr(media_svc.config, "COMFY_INPUT_DIR", input_dir)
    monkeypatch.setattr(media_svc.config, "REPO_ROOT", tmp_path)

    out = media_svc._media_to_html(str(f), output_kind="image")
    assert "/comfy_input/thumb.png" in out
    # 绝对不能是旧的 gradio_api 路由
    assert "gradio_api" not in out
    assert "/gradio_api/file=" not in out


def test_media_to_html_local_static_file_uses_static_route(tmp_path, monkeypatch):
    """app/static/ 下的本地文件 -> /static/<rel>, 不是 /gradio_api/file=."""
    static_dir = tmp_path / "app" / "static"
    static_dir.mkdir(parents=True)
    f = static_dir / "example.png"
    f.write_bytes(b"x")
    monkeypatch.setattr(media_svc.config, "REPO_ROOT", tmp_path)

    out = media_svc._media_to_html(str(f), output_kind="image")
    assert "/static/example.png" in out
    assert "gradio_api" not in out


def test_media_to_html_local_video_in_comfy_input(tmp_path, monkeypatch):
    """本地视频文件在 COMFY_INPUT_DIR -> /comfy_input/<name> + <video> 标签."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    f = input_dir / "clip.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(media_svc.config, "COMFY_INPUT_DIR", input_dir)
    monkeypatch.setattr(media_svc.config, "REPO_ROOT", tmp_path)

    out = media_svc._media_to_html(str(f), output_kind="video")
    assert "<video" in out
    assert "/comfy_input/clip.mp4" in out
    assert "gradio_api" not in out


def test_media_to_html_unrouted_local_file_falls_back_to_banner(tmp_path, monkeypatch):
    """既不在 COMFY_INPUT_DIR 也不在 app/static/ 的本地文件 -> 兜底 banner.

    模拟 ComfyUI output 目录的本地路径 (Flask 没路由服务它).
    """
    other = tmp_path / "output"
    other.mkdir()
    f = other / "result.xyz"
    f.write_bytes(b"x")
    monkeypatch.setattr(media_svc.config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(media_svc.config, "COMFY_INPUT_DIR", tmp_path / "input")

    out = media_svc._media_to_html(str(f), output_kind="video")
    # 没有路由能服务 -> 走兜底 banner
    assert "未知输出格式" in out
    assert "gradio_api" not in out


def test_file_route_prefix_is_no_longer_gradio():
    """模块级常量锁: 不再是 /gradio_api/file=."""
    assert media_svc._FILE_ROUTE_PREFIX != "/gradio_api/file="
    assert "gradio_api" not in media_svc._FILE_ROUTE_PREFIX
