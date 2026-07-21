"""音频 preset (qwen3_tts / ace_step_15_music) 的契约测试。

锁的内容：
1. 2 个 preset 都在 params.json 里存在
2. 对应 workflow JSON 文件存在
3. workflow 通过 validator
4. example 满足 example-must-have-example 契约
5. output_kind == audio
6. _media_to_html 能为 audio 渲染 <audio> 标签
7. select 类型 (language / model_choice / keyscale) 的 dropdown 渲染正确
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest
import gradio as gr

from app import config, scail2_app
from app.scail2_app import parse_sizes


AUDIO_PRESETS = ["qwen3_tts", "ace_step_15_music"]


@pytest.mark.parametrize("preset", AUDIO_PRESETS)
def test_audio_preset_exists_in_params(preset):
    cfg = config.preset_config(preset)
    assert "user_facing_inputs" in cfg
    assert cfg.get("output_kind") == "audio"
    assert cfg.get("category") == "audio"


@pytest.mark.parametrize("preset", AUDIO_PRESETS)
def test_audio_preset_workflow_validates(preset):
    wf = json.load(config.workflow_path(preset).open(encoding="utf-8"))
    cfg = config.preset_config(preset)
    from app.workflow_validator import validate
    validate(wf, cfg)


@pytest.mark.parametrize("preset", AUDIO_PRESETS)
def test_audio_preset_has_preview_audio(preset):
    """audio preset 的 example 必须有 preview_audio 路径。"""
    cfg = config.preset_config(preset)
    example = cfg.get("example", {})
    assert example.get("preview_audio"), f"{preset}: 缺 preview_audio"
    # preview_audio 路径应该存在
    p = REPO_ROOT / example["preview_audio"]
    assert p.exists(), f"{preset}: preview_audio 路径不存在: {p}"


def test_qwen3_tts_has_select_for_language_and_model():
    """qwen3_tts 暴露 language + model_choice 的 select (dropdown) 选项。"""
    cfg = config.preset_config("qwen3_tts")
    select_specs = [s for s in cfg["user_facing_inputs"] if s["type"] == "select"]
    fields = {s["field"] for s in select_specs}
    assert "language" in fields, "qwen3_tts 应有 language select"
    assert "model_choice" in fields, "qwen3_tts 应有 model_choice select"
    # language 选项至少含 Chinese / English
    lang_spec = next(s for s in select_specs if s["field"] == "language")
    assert "Chinese" in lang_spec["choices"]
    assert "English" in lang_spec["choices"]
    # model_choice 是 0.6B / 1.7B
    mc_spec = next(s for s in select_specs if s["field"] == "model_choice")
    assert "0.6B" in [c["value"] if isinstance(c, dict) else c for c in mc_spec["choices"]]
    assert "1.7B" in [c["value"] if isinstance(c, dict) else c for c in mc_spec["choices"]]


def test_ace_step_has_select_for_language_and_keyscale():
    """ace_step_15_music 暴露 language + keyscale 的 select 选项。"""
    cfg = config.preset_config("ace_step_15_music")
    select_specs = [s for s in cfg["user_facing_inputs"] if s["type"] == "select"]
    fields = {s["field"] for s in select_specs}
    assert "language" in fields
    assert "keyscale" in fields
    # keyscale 含 major / minor
    ks_spec = next(s for s in select_specs if s["field"] == "keyscale")
    choices_str = " ".join(c if isinstance(c, str) else c["value"] for c in ks_spec["choices"])
    assert "major" in choices_str
    assert "minor" in choices_str


def test_audio_form_renders_dropdown_for_select():
    """select type 在 UI 上渲染成 gr.Dropdown。"""
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("qwen3_tts")
    dropdowns = [b for b in demo.blocks.values() if isinstance(b, gr.Dropdown)]
    assert len(dropdowns) >= 2, f"qwen3_tts 至少应有 2 个 Dropdown (language + model_choice), 实际 {len(dropdowns)}"
    # 第一个 dropdown 的 value 是 Chinese (来自 example)
    assert dropdowns[0].value == "Chinese"


def test_audio_form_has_no_file_inputs():
    """audio preset 不应暴露 file:image / file:video 槽位 (无 file 上传步骤)。"""
    for preset in AUDIO_PRESETS:
        with gr.Blocks() as demo:
            scail2_app._render_workflow_form(preset)
        files = [b for b in demo.blocks.values() if isinstance(b, gr.File)]
        assert not files, f"{preset} 不应暴露 file 槽位, 实际 {len(files)} 个 gr.File"


def test_audio_output_kind_helper():
    """_output_kind 对 audio preset 返 audio, 对 video preset 返 video, 对 image preset 返 image。"""
    from app.scail2_app import _output_kind
    assert _output_kind({"output_kind": "audio"}) == "audio"
    assert _output_kind({"output_kind": "video"}) == "video"
    assert _output_kind({"output_kind": "image"}) == "image"
    # 没设 output_kind 时, 走 category 字段
    assert _output_kind({"category": "audio"}) == "audio"
    assert _output_kind({"category": "image"}) == "image"
    # 默认 video (向后兼容)
    assert _output_kind({}) == "video"
    assert _output_kind({"category": "other"}) == "video"


def test_media_to_html_renders_audio_for_mp3():
    """.mp3 URL / 本地路径 → <audio> 标签。"""
    # 1) HTTP URL
    html = scail2_app._media_to_html("http://x:8188/view?filename=test.mp3&type=output&subfolder=", output_kind="audio")
    assert "<audio" in html, f"mp3 URL 应渲染 <audio> 标签, 实际: {html[:200]}"
    assert "controls" in html
    # 2) 本地路径 (用 .mp3 真实文件)
    p = REPO_ROOT / "app" / "static" / "examples" / "qwen3_tts.mp3"
    html = scail2_app._media_to_html(str(p), output_kind="audio")
    assert "<audio" in html, f"本地 mp3 应渲染 <audio> 标签, 实际: {html[:200]}"
    assert "/gradio_api/file=" in html


def test_media_to_html_image_preset_still_renders_img():
    """image preset 的 png URL 仍渲染 <img> (向后兼容, 没回归)。"""
    html = scail2_app._media_to_html("http://x:8188/view?filename=test.png&type=output", output_kind="image")
    assert "<img" in html


def test_media_to_html_video_preset_still_renders_video():
    """video preset 的 mp4 URL 仍渲染 <video>。"""
    html = scail2_app._media_to_html("http://x:8188/view?filename=test.mp4&type=output", output_kind="video")
    assert "<video" in html


# ===== image/video preset 共用契约 (从源仓库 e:/cc/comfyui 同步) =====

NEW_PRESETS = ["qwen_image_2512_4step", "klein_edit", "ltx_23_t2v_distill", "ltx_23_i2v_distilled"]
VIDEO_PRESETS = ["ltx_23_t2v_distill", "ltx_23_i2v_distilled"]
ALL_NEW = NEW_PRESETS + AUDIO_PRESETS


@pytest.mark.parametrize("preset", NEW_PRESETS)
def test_new_preset_exists_in_params(preset):
    cfg = config.preset_config(preset)
    assert "user_facing_inputs" in cfg
    assert "workflow_file" in cfg
    assert "display_name" in cfg


@pytest.mark.parametrize("preset", NEW_PRESETS)
def test_new_preset_workflow_file_exists(preset):
    p = config.workflow_path(preset)
    assert p.exists(), f"{preset}.json missing at {p}"


@pytest.mark.parametrize("preset", ALL_NEW)
def test_new_preset_workflow_validates(preset):
    wf = json.load(config.workflow_path(preset).open(encoding="utf-8"))
    cfg = config.preset_config(preset)
    from app.workflow_validator import validate
    validate(wf, cfg)


@pytest.mark.parametrize("preset", ALL_NEW)
def test_new_preset_user_facing_match_workflow(preset):
    wf = json.load(config.workflow_path(preset).open(encoding="utf-8"))
    cfg = config.preset_config(preset)
    for spec in cfg["user_facing_inputs"]:
        nid = str(spec["node_id"])
        assert nid in wf


@pytest.mark.parametrize("preset", ALL_NEW)
def test_new_preset_example_present(preset):
    cfg = config.preset_config(preset)
    example = cfg.get("example", {})
    assert example
    assert example.get("preview_image") or example.get("preview_video") or example.get("preview_audio")


@pytest.mark.parametrize("preset", VIDEO_PRESETS)
def test_video_preset_has_both_previews(preset):
    cfg = config.preset_config(preset)
    example = cfg["example"]
    assert example.get("preview_image")
    assert example.get("preview_video")
    assert cfg.get("output_kind") == "video"


def test_qwen_image_sizes_presets_labeled():
    cfg = config.preset_config("qwen_image_2512_4step")
    spec = next(s for s in cfg["user_facing_inputs"] if s["type"] == "image_sizes")
    presets = spec["presets"]
    assert presets
    for p in presets:
        assert isinstance(p, dict)
        assert "label" in p and "value" in p
        assert any(tok in p["label"] for tok in ("16:9", "9:16", "1:1", "2:3", "4:3", "3:4", "横", "竖", "方", "正", "海", "封"))
        assert parse_sizes(p["value"]) is not None


def test_qwen_image_prompt_in_example_matches_default():
    cfg = config.preset_config("qwen_image_2512_4step")
    prompt = cfg["example"].get("prompt", "")
    assert "春日踏青" in prompt or "踏青" in prompt


def test_klein_edit_no_sizes_field():
    cfg = config.preset_config("klein_edit")
    for spec in cfg["user_facing_inputs"]:
        assert spec["type"] != "image_sizes"


def test_ltx_t2v_has_width_and_height_int_fields():
    cfg = config.preset_config("ltx_23_t2v_distill")
    int_specs = [s for s in cfg["user_facing_inputs"] if s["type"] == "int"]
    fields = {(s["node_id"], s["field"]) for s in int_specs}
    assert ("111", "width") in fields
    assert ("111", "height") in fields


def test_ltx_i2v_no_width_height_user_facing():
    cfg = config.preset_config("ltx_23_i2v_distilled")
    for spec in cfg["user_facing_inputs"]:
        field = spec.get("field", "")
        assert field not in ("width", "height")


@pytest.mark.parametrize("preset", ALL_NEW)
def test_new_preset_output_kind_matches_workflow(preset):
    cfg = config.preset_config(preset)
    wf = json.load(config.workflow_path(preset).open(encoding="utf-8"))
    class_types = {n.get("class_type") for n in wf.values()}
    has_video = bool(class_types & {"VHS_VideoCombine", "VHS_SaveVideo", "SaveWEBM", "CreateVideo"})
    has_image = bool(class_types & {"SaveImage", "PreviewImage"})
    has_audio = bool(class_types & {"SaveAudioMP3", "SaveAudio", "SaveAudioWav"})
    kind = cfg.get("output_kind")
    if kind == "video":
        assert has_video
    elif kind == "image":
        assert has_image
    elif kind == "audio":
        assert has_audio


@pytest.mark.parametrize("preset", ALL_NEW)
def test_new_preset_workflow_path_is_relative(preset):
    cfg = config.preset_config(preset)
    wf_path = cfg["workflow_file"]
    assert not Path(wf_path).is_absolute()


@pytest.mark.parametrize("preset", ALL_NEW)
def test_new_preset_output_box_renders_gradio_api_route(preset):
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form(preset)
    output_boxes = [
        b for b in demo.blocks.values()
        if isinstance(b, gr.HTML) and "result-area" in (getattr(b, "elem_classes", None) or [])
    ]
    assert len(output_boxes) == 1
    val = output_boxes[0].value or ""
    assert not any(d + ":" in val for d in "CDEFGHIJKLMNOPQRSTUVWXYZ")
    assert "src='/gradio_api/file=" in val


def test_run_workflow_preserves_fields_that_share_one_node(monkeypatch):
    """Qwen3-TTS fields on node 38 must not overwrite each other."""
    captured = {}

    monkeypatch.setattr(scail2_app, "validate_inputs", lambda *args: None)
    monkeypatch.setattr(scail2_app.scail2_client, "load_workflow_template", lambda preset: {"38": {"inputs": {}}})
    monkeypatch.setattr(scail2_app.scail2_client, "patch_workflow", lambda workflow, replacements, **kwargs: captured.update(replacements) or workflow)
    monkeypatch.setattr(scail2_app.scail2_client, "queue_prompt", lambda *args, **kwargs: ("prompt-1", "client-1"))
    monkeypatch.setattr(scail2_app.scail2_client, "wait_for_completion", lambda *args, **kwargs: iter(["stop after patch"]))
    monkeypatch.setattr(scail2_app.scail2_client, "start_progress_listener", lambda *args, **kwargs: __import__("queue").Queue())

    values = ("Hello", "calm voice", "English", "0.6B", 123)
    list(scail2_app.run_workflow("qwen3_tts", *values))

    assert captured["38"] == {
        "text": "Hello",
        "instruct": "calm voice",
        "language": "English",
        "model_choice": "0.6B",
        "seed": 123,
    }


def test_run_workflow_consumes_int_random_checkbox_and_value(monkeypatch, tmp_path):
    """Klein int_random consumes two components and patches the numeric seed."""
    captured = {}
    image = tmp_path / "person.png"
    image.write_bytes(b"png")

    monkeypatch.setattr(scail2_app, "validate_inputs", lambda *args: None)
    monkeypatch.setattr(scail2_app, "_resolve_upload_name", lambda *args, **kwargs: "person.png")
    monkeypatch.setattr(scail2_app.scail2_client, "load_workflow_template", lambda preset: {str(n): {"inputs": {}} for n in (76, 108, 109, 146)})
    monkeypatch.setattr(scail2_app.scail2_client, "patch_workflow", lambda workflow, replacements, **kwargs: captured.update(replacements) or workflow)
    monkeypatch.setattr(scail2_app.scail2_client, "queue_prompt", lambda *args, **kwargs: ("prompt-2", "client-2"))
    monkeypatch.setattr(scail2_app.scail2_client, "wait_for_completion", lambda *args, **kwargs: iter(["stop after patch"]))
    monkeypatch.setattr(scail2_app.scail2_client, "start_progress_listener", lambda *args, **kwargs: __import__("queue").Queue())

    values = (str(image), "silver armor", "no blur", False, 456)
    list(scail2_app.run_workflow("klein_edit", *values))

    assert captured["108"]["text"] == "silver armor"
    assert captured["109"]["text"] == "no blur"
    assert captured["146"]["seed"] == 456


def test_klein_form_uses_generic_runner(monkeypatch):
    """Image edit has no image_sizes field, so it must not use the text-to-image runner."""
    calls = []

    def image_runner(*args):
        calls.append("image")
        yield "stop", None

    def generic_runner(*args):
        calls.append("generic")
        yield "stop", None

    monkeypatch.setattr(scail2_app, "run_image_workflow", image_runner)
    monkeypatch.setattr(scail2_app, "run_workflow", generic_runner)
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("klein_edit")
    run_and_format = next(entry.fn for entry in demo.fns.values() if getattr(entry.fn, "__name__", "") == "_run_and_format")
    list(run_and_format(None, "prompt", "", False, 123))

    assert calls == ["generic"]


def test_generic_image_runner_extracts_save_image_output(monkeypatch, tmp_path):
    """Klein success history exposes images, which must become a browser preview URL."""
    image = tmp_path / "person.png"
    image.write_bytes(b"png")
    workflow = {str(n): {"inputs": {}} for n in (76, 108, 109, 146)}
    result_history = {"outputs": {"1": {"images": [{"filename": "edit.png", "subfolder": "", "type": "output"}]}}}

    monkeypatch.setattr(scail2_app, "validate_inputs", lambda *args: None)
    monkeypatch.setattr(scail2_app, "_resolve_upload_name", lambda *args, **kwargs: "person.png")
    monkeypatch.setattr(scail2_app.scail2_client, "load_workflow_template", lambda preset: workflow)
    monkeypatch.setattr(scail2_app.scail2_client, "patch_workflow", lambda workflow, replacements, **kwargs: workflow)
    monkeypatch.setattr(scail2_app.scail2_client, "queue_prompt", lambda *args, **kwargs: ("prompt-image", "client-image"))
    monkeypatch.setattr(scail2_app.scail2_client, "wait_for_completion", lambda *args, **kwargs: iter(["✅ done"]))
    monkeypatch.setattr(scail2_app.scail2_client, "start_progress_listener", lambda *args, **kwargs: __import__("queue").Queue())
    monkeypatch.setattr(scail2_app.scail2_client, "get_history", lambda *args: result_history)
    monkeypatch.setattr(scail2_app.history, "write_manifest", lambda *args, **kwargs: None)

    yields = list(scail2_app.run_workflow("klein_edit", str(image), "silver armor", "", False, 456))

    assert any(media and "edit.png" in media for _, media in yields)


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("qwen3_tts", ["speech_text", "instruct", "language", "model_choice", "seed"]),
        ("ace_step_15_music", ["tags", "lyrics", "bpm", "duration", "language", "keyscale", "seed"]),
    ],
)
def test_audio_example_values_fill_every_declared_field(preset, expected):
    """Load-example values must come from example, not shorter schema defaults."""
    cfg = config.preset_config(preset)
    values = scail2_app.example_to_form_values(preset)

    assert values == [cfg["example"][key] for key in expected]
