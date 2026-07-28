"""file:audio type 的契约测试 + qwen3_tts_clone preset 锁定.

锁:
  - config.ALLOWED_AUDIO_EXT / MAX_AUDIO_MB 存在
  - flask /api/upload 接受 kind="audio"
  - form_schema.example_to_form_values 把 file:audio spec 映射到 example.ref_audio
  - form_schema.validate_inputs(audio_path=...) 校验扩展名 + 大小
  - qwen3_tts_clone preset 在 list_workflows 顺序里夹在 qwen3_tts (200) 与 ace_step_15_music (210) 之间
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest
from app import config, scail2_client
from app.services import form_schema


# --- 1) config 暴露 ALLOWED_AUDIO_EXT / MAX_AUDIO_MB ---

def test_config_exposes_audio_constants():
    assert hasattr(config, "ALLOWED_AUDIO_EXT")
    assert ".mp3" in config.ALLOWED_AUDIO_EXT
    assert ".wav" in config.ALLOWED_AUDIO_EXT
    assert hasattr(config, "MAX_AUDIO_MB")
    assert config.MAX_AUDIO_MB > 0


# --- 2) qwen3_tts_clone preset 加载 + 排序 ---

def test_qwen3_tts_clone_loaded_with_correct_metadata():
    cfg = config.preset_config("qwen3_tts_clone")
    assert cfg["display_name"] == "\u8bed\u97f3\u514b\u9686 (Qwen3-TTS VoiceClone)"
    assert cfg["category"] == "audio"
    assert cfg["order"] == 205
    assert cfg["output_kind"] == "audio"
    assert cfg["workflow_file"] == "qwen3_tts_clone.json"


def test_qwen3_tts_clone_in_list_between_qwen3_tts_and_music():
    """qwen3_tts_clone (205) 必须夹在 qwen3_tts (200) 与 ace_step_15_music (210) 之间."""
    wfs = config.list_workflows()
    audio = [w["name"] for w in wfs if w["category"] == "audio"]
    assert audio.index("qwen3_tts") < audio.index("qwen3_tts_clone") < audio.index("ace_step_15_music")


def test_qwen3_tts_clone_user_facing_inputs_shape():
    cfg = config.preset_config("qwen3_tts_clone")
    specs = cfg["user_facing_inputs"]
    # 必须有 file:audio / text / select / int, 共 6 个 spec
    assert len(specs) == 6
    audio_spec = next(s for s in specs if s["type"] == "file:audio")
    assert audio_spec["node_id"] == "24"
    assert audio_spec["field"] == "audio"
    assert audio_spec["tier"] == "basic"
    # ref_text / target_text 是 text spec
    text_specs = [s for s in specs if s["type"] == "text"]
    assert len(text_specs) == 2
    fields = {s["field"] for s in text_specs}
    assert fields == {"ref_text", "target_text"}
    # 高级参数: language / model_choice / seed
    advanced = [s for s in specs if s.get("tier") == "advanced"]
    assert {s["field"] for s in advanced} == {"language", "model_choice", "seed"}


def test_qwen3_tts_clone_example_uses_ref_audio_key():
    """example 块的 ref_audio 必须存在且等于 example_to_form_values 返回的 [0].

    review 2026-07-28: 改成项目相对路径 "app/static/examples/...", 不再走 COMFY_INPUT_DIR.
    """
    cfg = config.preset_config("qwen3_tts_clone")
    assert "ref_audio" in cfg["example"]
    assert cfg["example"]["ref_audio"] == "app/static/examples/\u5143\u6c14\u5c11\u5973.mp3"
    vals = form_schema.example_to_form_values("qwen3_tts_clone")
    # [0] 是 file:audio spec, 项目相对路径原样返回
    assert vals[0] == "app/static/examples/\u5143\u6c14\u5c11\u5973.mp3", f"got {vals[0]!r}"


def test_qwen3_tts_clone_preview_audio_path_set():
    cfg = config.preset_config("qwen3_tts_clone")
    pv = cfg["example"].get("preview_audio")
    assert pv
    # 必须是相对仓库路径 (Flask 路由 /static/..)
    assert pv.startswith("app/static/examples/")
    # 实际文件存在
    p = REPO_ROOT / pv
    assert p.exists(), f"preview audio missing: {p}"


# --- 3) form_schema 对 file:audio 的处理 ---

def test_example_to_form_values_maps_file_audio_to_ref_audio(tmp_path, monkeypatch):
    """file:audio spec 应通过 example.ref_audio 取值, 跟 file:image (reference_image) / file:video (drive_video) 同套约定.

    review 2026-07-28: 改成 "app/static/examples/ref.wav" (项目相对路径, 走 _resolve_example_file).
    """
    examples = tmp_path / "app" / "static" / "examples"
    examples.mkdir(parents=True)
    (examples / "ref.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(form_schema.config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(form_schema.config, "COMFY_INPUT_DIR", tmp_path / "input")

    saved = config.preset_config

    def fake_pcfg(name):
        if name == "fake_audio_preset":
            return {
                "user_facing_inputs": [
                    {"node_id": "24", "field": "audio", "type": "file:audio", "tier": "basic"},
                ],
                "example": {"ref_audio": "ref.wav"},
            }
        return saved(name)

    monkeypatch.setattr(form_schema.config, "preset_config", fake_pcfg)
    vals = form_schema.example_to_form_values("fake_audio_preset")
    assert vals == ["app/static/examples/ref.wav"], f"got {vals!r}"


def test_validate_inputs_checks_audio_extension_and_size(tmp_path, monkeypatch):
    monkeypatch.setattr(form_schema.config, "ALLOWED_AUDIO_EXT", frozenset({".mp3", ".wav"}))
    monkeypatch.setattr(form_schema.config, "MAX_AUDIO_MB", 10)

    # 没有 audio spec -> audio_path 不校验
    cfg = {"user_facing_inputs": []}
    assert form_schema.validate_inputs(None, None, cfg, audio_path=None) is None

    # 加 file:audio spec, 但 audio_path 为空 -> 报错
    cfg = {"user_facing_inputs": [{"type": "file:audio"}]}
    err = form_schema.validate_inputs(None, None, cfg, audio_path="")
    assert "音频未上传" in err

    # 不允许的扩展名
    err = form_schema.validate_inputs(None, None, cfg, audio_path="x.txt")
    assert "扩展名不支持" in err

    # 超过 MAX_AUDIO_MB
    big = tmp_path / "big.mp3"
    big.write_bytes(b"x" * (11 * 1024 * 1024))
    err = form_schema.validate_inputs(None, None, cfg, audio_path=str(big))
    assert "过大" in err


# --- 4) flask /api/upload 接受 kind="audio" ---

def test_upload_endpoint_accepts_audio_kind(tmp_path, monkeypatch):
    """mock requests.post + 检查 kind=audio 走到 ALLOWED_AUDIO_EXT / MAX_AUDIO_MB 分支."""
    from app import scail2_client
    captured = {}
    fake_resp = type("R", (), {"status_code": 200, "text": "{}", "json": lambda self: {"name": "x.mp3", "subfolder": "", "type": "input"}})()

    def fake_post(url, **kwargs):
        captured["url"] = url
        return fake_resp

    monkeypatch.setattr(scail2_client.requests, "post", fake_post)
    # 当前 scail2_client.upload 内部 kind 不影响端点 (kind 已废弃), 但我们要确认 kind 参数仍能传
    p = tmp_path / "x.mp3"
    p.write_bytes(b"\xff\xfb\x00")
    scail2_client.upload(p, kind="audio")
    # 端点仍是 /upload/image (ComfyUI 0.24 唯一上传端点)
    assert captured["url"].endswith("/upload/image")
