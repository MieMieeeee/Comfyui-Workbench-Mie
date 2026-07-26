"""wizard.py 单元测试 — 推断规则 + workflow 解析 + 输出提取.

推断规则用现有 preset 的真实 workflow JSON 验证 (zimage/klein_edit/sca12 等),
不发明假数据. 输出提取用构造的 history fixture 测多输出场景
(ltx_23_i2v 那种一 output 一 temp 的踩坑场景).
"""
import json
from pathlib import Path

from app.services import wizard

REPO_ROOT = Path(__file__).resolve().parent.parent
PRESETS = REPO_ROOT / "app" / "presets"


def _load_wf(name: str) -> dict:
    return json.loads((PRESETS / name).read_text(encoding="utf-8"))


# ============================================================
# infer_spec — 8 条推断规则
# ============================================================

def test_infer_connection_ref_returns_none():
    """node 间连接引用 [node_id, slot] 不是用户输入, 返回 None."""
    assert wizard.infer_spec("5", "mask", ["81", 0], "MaskPreview+") is None


def test_infer_loadimage_image_is_file_image():
    spec = wizard.infer_spec("196", "image", "model-10.png", "LoadImage")
    assert spec["type"] == "file:image"
    assert spec["label"] == "参考图"
    assert spec["confidence"] == "high"


def test_infer_vhs_loadvideo_video_is_file_video():
    spec = wizard.infer_spec("202", "video", "d6.mp4", "VHS_LoadVideo")
    assert spec["type"] == "file:video"
    assert spec["confidence"] == "high"


def test_infer_seed_is_int_random():
    """seed 字段默认 int_random (带随机复选框), 高置信度."""
    spec = wizard.infer_spec("3", "seed", 0, "KSampler")
    assert spec["type"] == "int_random"
    assert spec.get("random_default") is True
    assert spec["confidence"] == "high"


def test_infer_sizes_latent_width_height_is_image_sizes():
    """EmptySD3LatentImage 的 width/height → image_sizes (合并标记), 高置信度."""
    spec = wizard.infer_spec("13", "width", 1024, "EmptySD3LatentImage")
    assert spec["type"] == "image_sizes"
    assert spec.get("_merge_key") == "13"
    assert spec["confidence"] == "high"


def test_infer_bool_value_is_bool():
    spec = wizard.infer_spec("353", "value", False, "PrimitiveBoolean")
    assert spec["type"] == "bool"


def test_infer_int_value_is_int():
    spec = wizard.infer_spec("367", "value", 1, "PrimitiveInt")
    assert spec["type"] == "int"


def test_infer_string_value_is_text():
    spec = wizard.infer_spec("6", "text", "a prompt", "CLIPTextEncode")
    assert spec["type"] == "text"
    assert spec["confidence"] == "low"


def test_infer_long_clip_text_is_prompt_pool():
    """CLIPTextEncode.text + 长内容 (>20字符) → prompt_pool (中置信度, 像正向提示词)."""
    long_prompt = "Photorealistic, ultra-detailed portrait of a woman in a forest"
    spec = wizard.infer_spec("6", "text", long_prompt, "CLIPTextEncode")
    assert spec["type"] == "prompt_pool"
    assert spec["confidence"] == "medium"


def test_infer_short_clip_text_stays_text():
    """CLIPTextEncode.text + 短内容 (负向提示词 'blurry ugly bad') → text (低置信度)."""
    spec = wizard.infer_spec("7", "text", "blurry ugly bad", "CLIPTextEncode")
    assert spec["type"] == "text"
    assert spec["confidence"] == "low"


def test_infer_vhs_loadvideo_non_video_field_is_int():
    """VHS_LoadVideo 的 video → file:video, 但 frame_load_cap 等数字字段 → int."""
    spec = wizard.infer_spec("202", "frame_load_cap", 0, "VHS_LoadVideo")
    assert spec["type"] == "int"


# ============================================================
# parse_workflow_api_json — 真实 workflow 解析
# ============================================================

def test_parse_zimage_finds_prompt_sizes_seed():
    """zimage 应解析出: 长 prompt(prompt_pool medium), sizes(image_sizes high), seed(int_random high)."""
    raw = (PRESETS / "zimage.json").read_text(encoding="utf-8")
    result = wizard.parse_workflow_api_json(raw)
    # node 6 的正向 prompt 是长句 → prompt_pool (medium)
    prompt_specs = [f for f in result["fields"] if f["field"] == "text" and f["node_id"] == "6"]
    assert len(prompt_specs) == 1
    assert prompt_specs[0]["type"] == "prompt_pool"
    assert prompt_specs[0]["confidence"] == "medium"
    # node 3 seed → int_random (high)
    seed_specs = [f for f in result["fields"] if f["field"] == "seed"]
    assert seed_specs[0]["type"] == "int_random"
    assert seed_specs[0]["confidence"] == "high"
    # node 13 width+height 合并成 image_sizes (field="sizes"), 合并后仍是 high
    sizes_specs = [f for f in result["fields"] if f["type"] == "image_sizes"]
    assert len(sizes_specs) == 1
    assert sizes_specs[0]["confidence"] == "high"
    assert result["node_count"] == 9


def test_parse_klein_edit_finds_file_image():
    """klein_edit 有 LoadImage node 76 → file:image."""
    raw = (PRESETS / "klein_edit.json").read_text(encoding="utf-8")
    result = wizard.parse_workflow_api_json(raw)
    image_specs = [f for f in result["fields"] if f["type"] == "file:image"]
    assert len(image_specs) >= 1
    assert image_specs[0]["node_id"] == "76"


def test_parse_fields_include_node_context():
    """每个候选字段应带 node_title / class_type / current_value, 供向导 UI 显示.

    用户选输入项时需要看节点上下文 (光给 node_id '108' 分不清正向还是负向提示词,
    有 title 'CLIP Text Encode (Positive Prompt)' 才知道).
    """
    raw = (PRESETS / "klein_edit.json").read_text(encoding="utf-8")
    result = wizard.parse_workflow_api_json(raw)
    # 所有字段都带这三个上下文字段
    for f in result["fields"]:
        assert "node_title" in f, f"字段 {f.get('field')} 缺 node_title"
        assert "class_type" in f, f"字段 {f.get('field')} 缺 class_type"
        assert "current_value" in f, f"字段 {f.get('field')} 缺 current_value"
    # node 76 LoadImage 的 title 应该是 'Load Image'
    img = next(f for f in result["fields"] if f["node_id"] == "76" and f["field"] == "image")
    assert img["class_type"] == "LoadImage"
    assert img["node_title"]  # 非空
    assert img["current_value"]  # 非空 (图片文件名)
    # 正向提示词 node 108 的 title 含 'Positive'
    pos = next(f for f in result["fields"] if f["node_id"] == "108" and f["field"] == "text")
    assert "Positive" in pos["node_title"], f"正向提示词 title 不对: {pos['node_title']}"


def test_parse_liveportrait_finds_file_video_and_filters_connections():
    """liveportrait: VHS_LoadVideo → file:video; 连接引用被过滤."""
    raw = (PRESETS / "liveportrait.json").read_text(encoding="utf-8")
    result = wizard.parse_workflow_api_json(raw)
    video_specs = [f for f in result["fields"] if f["type"] == "file:video"]
    assert len(video_specs) >= 1
    # MaskPreview 的 mask 是连接引用, 不该出现在 fields 里
    for f in result["fields"]:
        assert f["field"] != "mask" or f["node_id"] != "82"


def test_parse_invalid_json_raises():
    import pytest
    with pytest.raises(ValueError):
        wizard.parse_workflow_api_json("not json")


# ============================================================
# extract_all_outputs — history 输出遍历
# ============================================================

def test_extract_all_outputs_multiple_nodes_and_types():
    """一次运行, 多个 node 各出不同类型产物, 全部收集."""
    history = {
        "outputs": {
            "9": {"images": [{"filename": "out1.png", "subfolder": "", "type": "output"}]},
            "456": {"videos": [{"filename": "final.mp4", "subfolder": "SCAIL-2", "type": "output"}]},
        }
    }
    results = wizard.extract_all_outputs(history, workflow=None)
    assert len(results) == 2
    # 按 node_id 排序: 9 在前
    assert results[0]["node_id"] == "9"
    assert results[0]["media_key"] == "images"
    assert results[1]["node_id"] == "456"
    assert results[1]["media_key"] == "videos"
    assert results[1]["subfolder"] == "SCAIL-2"
    # url 走 WebUI 同源代理，局域网浏览器不会访问自己的 127.0.0.1
    assert results[0]["url"].startswith("/comfy_output?")


def test_extract_all_outputs_includes_temp_products():
    """temp 产物也要收集 (不过滤), 让 UI 决定怎么标注."""
    history = {
        "outputs": {
            "150": {"videos": [{"filename": "half.mp4", "subfolder": "temp", "type": "temp"}]},
            "209": {"videos": [{"filename": "final.mp4", "subfolder": "", "type": "output"}]},
        }
    }
    results = wizard.extract_all_outputs(history, workflow=None)
    assert len(results) == 2
    types = {r["type"] for r in results}
    assert types == {"output", "temp"}


def test_extract_all_outputs_translates_node_title_from_workflow():
    """history 不带 title, 用 workflow 的 _meta.title 翻译 node_id."""
    history = {"outputs": {"456": {"videos": [{"filename": "v.mp4", "type": "output"}]}}}
    workflow = {"456": {"class_type": "VHS_VideoCombine", "_meta": {"title": "Video Combine 🎥"}}}
    results = wizard.extract_all_outputs(history, workflow=workflow)
    assert results[0]["title"] == "Video Combine 🎥"


def test_extract_all_outputs_empty_history():
    assert wizard.extract_all_outputs({}, workflow=None) == []
    assert wizard.extract_all_outputs({"outputs": {}}, workflow=None) == []


def test_extract_all_outputs_node_with_multiple_images():
    """一个 node 出多张图 (如 MaskPreview 多个 mask), 全收集."""
    history = {
        "outputs": {
            "82": {"images": [
                {"filename": "mask1.png", "type": "temp"},
                {"filename": "mask2.png", "type": "temp"},
            ]},
        }
    }
    results = wizard.extract_all_outputs(history, workflow=None)
    assert len(results) == 2
    assert all(r["node_id"] == "82" for r in results)


# ============================================================
# build_replacements — 向导 spec+values → ComfyUI replacements
# ============================================================

def test_build_replacements_text_field():
    fields = [{"node_id": "6", "field": "text", "type": "text", "default": "fallback"}]
    reps = wizard.build_replacements(fields, {"text": "hello"})
    assert reps == {"6": {"text": "hello"}}


def test_build_replacements_text_falls_back_to_default():
    """values 没给的字段用 spec.default."""
    fields = [{"node_id": "6", "field": "text", "type": "text", "default": "fallback"}]
    reps = wizard.build_replacements(fields, {})
    assert reps == {"6": {"text": "fallback"}}


def test_build_replacements_int_field():
    fields = [{"node_id": "367", "field": "value", "type": "int", "default": 1}]
    reps = wizard.build_replacements(fields, {"value": 5})
    assert reps == {"367": {"value": 5}}


def test_build_replacements_image_sizes_expands_to_width_height():
    """image_sizes 字段 → 拆成 width/height/batch_size (取第一个尺寸)."""
    fields = [{"node_id": "13", "field": "sizes", "type": "image_sizes", "default": ["1024x1024"]}]
    reps = wizard.build_replacements(fields, {"sizes": ["720x1280"]})
    assert reps == {"13": {"width": 720, "height": 1280, "batch_size": 1}}


def test_build_replacements_file_field():
    fields = [{"node_id": "76", "field": "image", "type": "file:image", "default": None}]
    reps = wizard.build_replacements(fields, {"image": "photo.png"})
    assert reps == {"76": {"image": "photo.png"}}


def test_build_replacements_file_field_none_skipped():
    """file 字段值为空时不写进 replacements (让 workflow 用默认)."""
    fields = [{"node_id": "76", "field": "image", "type": "file:image", "default": None}]
    reps = wizard.build_replacements(fields, {"image": None})
    assert reps == {}


def test_build_replacements_merges_same_node_fields():
    """同一个 node 的多个 field 合并到同一个 replacements[node_id]."""
    fields = [
        {"node_id": "94", "field": "tags", "type": "text", "default": ""},
        {"node_id": "94", "field": "lyrics", "type": "text", "default": ""},
    ]
    reps = wizard.build_replacements(fields, {"tags": "rock", "lyrics": "la la"})
    assert reps == {"94": {"tags": "rock", "lyrics": "la la"}}


def test_run_workflow_once_uses_client_timeout_sec(monkeypatch):
    """向导试跑应使用客户端当前的 timeout_sec 参数名。"""
    from app import scail2_client

    calls = {}
    history = {"outputs": {}}

    def fake_patch(workflow, replacements, validate_after=True):
        calls["patch"] = (workflow, replacements, validate_after)
        return {"patched": True}

    def fake_wait(prompt_id, **kwargs):
        calls["wait"] = (prompt_id, kwargs)
        return iter(["done"])

    monkeypatch.setattr(scail2_client, "patch_workflow", fake_patch)
    monkeypatch.setattr(scail2_client, "queue_prompt", lambda workflow: ("prompt-1", "client-1"))
    monkeypatch.setattr(scail2_client, "wait_for_completion", fake_wait)
    monkeypatch.setattr(scail2_client, "get_history", lambda prompt_id: history)

    result = wizard.run_workflow_once({"1": {}}, {"1": {"text": "hello"}})

    assert result is history
    assert calls["patch"] == ({"1": {}}, {"1": {"text": "hello"}}, False)
    assert calls["wait"] == ("prompt-1", {"timeout_sec": 600})


def test_parse_empty_latent_image_merges_width_height():
    workflow = {"6": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 768, "batch_size": 1}}}
    result = wizard.parse_workflow_api_json(workflow)
    sizes = [f for f in result["fields"] if f["type"] == "image_sizes"]
    assert len(sizes) == 1
    assert sizes[0]["default"] == ["1024x768"]
    assert sizes[0]["help"]
    assert sizes[0]["presets"]


def test_prepare_example_maps_defaults_and_copies_selected_output(tmp_path, monkeypatch):
    from app import config, scail2_client
    source = tmp_path / "ComfyUI" / "output" / "Krea2" / "k2_0001.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"png-data")
    monkeypatch.setattr(config, "COMFY_OUTPUT_DIR", tmp_path / "ComfyUI" / "output")
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(scail2_client, "get_output_url", lambda *args: "unused")
    fields = [
        {"node_id": "19", "field": "value", "type": "text", "default": "a cat"},
        {"node_id": "6", "field": "sizes", "type": "image_sizes", "default": ["1024x1024"]},
        {"node_id": "9", "field": "seed", "type": "int_random", "default": 77},
    ]
    output = {"filename": "k2_0001.png", "subfolder": "Krea2", "type": "output", "media_key": "images"}
    example = wizard.prepare_example("t2i_krea2", fields, {}, output)
    assert example["value"] == "a cat"
    assert example["sizes"] == ["1024x1024"]
    assert example["seed"] == 77
    assert example["preview_image"] == "app/static/examples/t2i_krea2.png"
    assert (tmp_path / "repo" / "app" / "static" / "examples" / "t2i_krea2.png").read_bytes() == b"png-data"


def test_prepare_example_rejects_output_outside_comfy_root(tmp_path, monkeypatch):
    import pytest
    from app import config
    monkeypatch.setattr(config, "COMFY_OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path / "repo")
    output = {"filename": "escape.png", "subfolder": "../outside", "type": "output", "media_key": "images"}
    with pytest.raises(ValueError, match="输出路径"):
        wizard.prepare_example("unsafe", [], {}, output)
