"""UI helper 单元测试：last_run 持久化、category icon、media HTML 渲染、status text。

这些 helper 都是上轮 UI 重构新增的，独立于 build_ui 测试，能跑得更快、
定位更准。e2e 渲染测试见 tests/test_e2e_render.py。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import config, scail2_app


# ---- _save_last_run / _load_last_run round-trip ----

def test_last_run_save_and_load_roundtrip(tmp_path, monkeypatch):
    """写一组混合类型值，再读回，列表对齐 + 内容相等。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    values = [None, "hello world", 42, 3.14, True, [1, 2, "x"], {"k": "v"}, "/some/path.png"]
    scail2_app._save_last_run("sca12_replace", values)

    out = scail2_app._load_last_run("sca12_replace", len(values))
    assert out == values


def test_load_last_run_missing_returns_all_none(tmp_path, monkeypatch):
    """没写过这个 preset -> 全 None。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    out = scail2_app._load_last_run("never_saved_preset", 5)
    assert out == [None] * 5


def test_load_last_run_pads_when_too_short(tmp_path, monkeypatch):
    """存的列表比当前 n_inputs 短 -> 后补 None。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    (tmp_path / "short.json").write_text(json.dumps([1, 2]), encoding="utf-8")
    out = scail2_app._load_last_run("short", 5)
    assert out == [1, 2, None, None, None]


def test_load_last_run_truncates_when_too_long(tmp_path, monkeypatch):
    """存的列表比当前 n_inputs 长 -> 截断。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    (tmp_path / "long.json").write_text(json.dumps([1, 2, 3, 4, 5]), encoding="utf-8")
    out = scail2_app._load_last_run("long", 3)
    assert out == [1, 2, 3]


def test_load_last_run_corrupt_returns_none(tmp_path, monkeypatch):
    """文件存在但 JSON 烂掉 -> 不崩，全 None。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    out = scail2_app._load_last_run("broken", 3)
    assert out == [None, None, None]


def test_load_last_run_non_list_returns_none(tmp_path, monkeypatch):
    """存的不是 list -> 全 None（防 schema 漂移）。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    (tmp_path / "dict.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    out = scail2_app._load_last_run("dict", 3)
    assert out == [None, None, None]


def test_save_last_run_serializes_unknown_object(tmp_path, monkeypatch):
    """遇到 gr.File 之类的非原生对象 -> str(v) 兜底，不崩。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    weird = MagicMock()
    weird.__str__ = lambda self: "<MagicMock>"
    scail2_app._save_last_run("weird", [weird])
    out = scail2_app._load_last_run("weird", 1)
    assert out == ["<MagicMock>"]


# ---- _category_icon ----

def test_category_icon_known_categories():
    assert scail2_app._category_icon("video") == chr(0x1F3AC)
    assert scail2_app._category_icon("image") == chr(0x1F5BC) + chr(0xFE0F)
    assert scail2_app._category_icon("audio") == chr(0x1F50A)
    assert scail2_app._category_icon("3d") == chr(0x1F9CA)
    assert scail2_app._category_icon("other") == chr(0x1F4E6)


def test_category_icon_unknown_falls_back_to_other():
    """未知 category 不能返回空串，要兜底成 📦。"""
    icon = scail2_app._category_icon("never_heard_of_it")
    assert icon == chr(0x1F4E6)


# ---- _media_to_html ----

def test_media_to_html_none_returns_placeholder():
    out = scail2_app._media_to_html(None, is_image=True)
    assert "等待结果" in out
    assert "padding" in out


def test_media_to_html_empty_image_list_returns_placeholder():
    out = scail2_app._media_to_html([], is_image=True)
    assert "等待结果" in out


def test_media_to_html_single_image_url():
    out = scail2_app._media_to_html("http://x/y.png", is_image=True)
    assert "<img" in out
    assert "y.png" in out
    assert "max-width:100%" in out


def test_media_to_html_image_list_grid():
    urls = ["http://x/a.png", "http://x/b.png", "http://x/c.png"]
    out = scail2_app._media_to_html(urls, is_image=True)
    # 3 张图，每张都有 <img
    assert out.count("<img") == 3
    # 每张都用网格宽度 32%
    assert out.count("max-width:32%") == 3


def test_media_to_html_video_url_uses_video_tag():
    out = scail2_app._media_to_html("http://x/clip.mp4", is_image=False)
    assert "<video" in out
    assert "controls" in out
    assert "clip.mp4" in out


def test_media_to_html_unknown_http_url_falls_back_to_banner():
    """不在 image/video 扩展名里的 URL -> .file-fallback banner。"""
    out = scail2_app._media_to_html("http://x/output.glb", is_image=False)
    assert "file-fallback" in out
    assert "output.glb" in out or "未知" in out


def test_media_to_html_image_extension_video_context_still_image():
    """is_image=False 但 URL 是图片扩展名 -> 仍走 <img>，不会被当视频。"""
    out = scail2_app._media_to_html("http://x/a.png", is_image=False)
    assert "<img" in out
    assert "<video" not in out


def test_media_to_html_empty_src_returns_placeholder():
    out = scail2_app._media_to_html([""], is_image=False)
    assert "等待结果" in out


# ---- _comfy_status_text ----

def test_comfy_status_text_ok_green_dot():
    with patch("app.scail2_client.check_connection", return_value=(True, "ok")), \
         patch("app.scail2_client.get_base_url", return_value="http://127.0.0.1:8188"):
        text = scail2_app._comfy_status_text()
    assert chr(0x1F7E2) in text
    assert "127.0.0.1:8188" in text


def test_comfy_status_text_down_red_dot():
    with patch("app.scail2_client.check_connection", return_value=(False, "no")), \
         patch("app.scail2_client.get_base_url", return_value="http://127.0.0.1:8188"):
        text = scail2_app._comfy_status_text()
    assert chr(0x1F534) in text
    assert "127.0.0.1:8188" in text


def test_comfy_status_text_handles_exception():
    """check_connection 抛异常时不能崩，应该走红点分支。"""
    with patch("app.scail2_client.check_connection", side_effect=RuntimeError("boom")), \
         patch("app.scail2_client.get_base_url", return_value="http://x"):
        text = scail2_app._comfy_status_text()
    assert chr(0x1F534) in text


# ---- _open_output_dir_action ----

def test_open_output_dir_action_creates_dir_and_returns_status(monkeypatch, tmp_path):
    """点 📂 -> 创建目录 + 调 Popen（不实际打开系统文件管理器）+ 返回状态文字。"""
    monkeypatch.setattr(config, "COMFY_OUTPUT_DIR", tmp_path / "outputs")
    fake_popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    # 仅在 windows 上要 explorer；跨平台 Popen 路径不同，这里统一 patch 掉。
    msg = scail2_app._open_output_dir_action()
    assert (tmp_path / "outputs").exists()
    # 返回文案是 "已打开: {path}"
    assert "已打开" in msg
    assert "outputs" in msg
    # Popen 至少被调一次（参数因平台而异，不细校验）
    assert fake_popen.called


# ---- _render_workflow_form has_expected_state_buttons ----

def test_render_workflow_form_creates_load_last_btn_per_preset():
    """每个 preset 都应有一个 '📂 加载上次成功参数' 按钮（不一定 visible，取决于 has_last_run）。"""
    import gradio as gr
    from app import config as cfg
    workflows = cfg.list_workflows()
    assert workflows, "需要至少一个 preset"
    for w in workflows:
        with gr.Blocks() as demo:
            scail2_app._render_workflow_form(w["name"])
        labels = [str(getattr(b, "value", "") or "") for b in demo.blocks.values()]
        # 按钮 label 写在 gr.Button(value=...)
        any_last_btn = any("加载上次成功参数" in lbl for lbl in labels)
        assert any_last_btn, f"{w['name']} 缺少 '📂 加载上次成功参数' 按钮"


def test_render_workflow_form_creates_status_accordion():
    """📜 运行日志 Accordion 每个 preset 都要有（advanced 折叠区可以有，但这个不能少）。"""
    import gradio as gr
    from app import config as cfg
    workflows = cfg.list_workflows()
    for w in workflows:
        with gr.Blocks() as demo:
            scail2_app._render_workflow_form(w["name"])
        # Accordion 的 label 在 .label 字段
        accordion_labels = [str(getattr(b, "label", "") or "") for b in demo.blocks.values()
                            if isinstance(b, gr.Accordion)]
        assert any("运行日志" in lbl for lbl in accordion_labels), \
            f"{w['name']} 缺 '📜 运行日志' Accordion"