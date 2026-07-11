"""file:video 的 also_patch 行为单测。

覆盖：
- 同一份 drive_name 写到主 node + also_patch 列出的 node
- also_patch: [] 退化为只 patch 主 node
- 主 node id 出现在 also_patch 时（异常配置）不丢主字段
- workflow_validator 不去校验 also_patch 列出的 node（schema 边界）
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app, workflow_validator


def _fake_history_success():
    return {
        "status": {"completed": True, "status_str": "success", "messages": []},
        "outputs": {"9": {"videos": [{"filename": "out.mp4", "subfolder": "SCAIL-2", "type": "output"}]}},
    }


def _make_ref_and_drive(tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG")
    drive = tmp_path / "drive.mp4"
    drive.write_bytes(b"\x00\x00\x00 mp4")
    return ref, drive


def _collect(gen):
    msgs, urls = [], []
    for s, u in gen:
        msgs.append(s); urls.append(u)
    return msgs, urls


def _synthetic_workflow() -> dict:
    return {
        "30":  {"inputs": {"image": "x"}, "class_type": "LoadImage"},
        "362": {"inputs": {"text": ""}, "class_type": "CLIPTextEncode"},
        "369": {"inputs": {"video": "old.mp4"}, "class_type": "VHS_LoadVideo"},
        "348": {"inputs": {"text": ""}, "class_type": "CLIPTextEncode"},
        "360": {"inputs": {"text": ""}, "class_type": "CLIPTextEncode"},
        "367": {"inputs": {"value": 0}, "class_type": "PrimitiveInt"},
        "464": {"inputs": {"value": 0}, "class_type": "PrimitiveInt"},
        "479": {"inputs": {"value": 0}, "class_type": "PrimitiveInt"},
        "469": {"inputs": {"video": "old.mp4"}, "class_type": "LoadVideo"},
        "9":   {"inputs": {}, "class_type": "VHS_VideoCombine"},
    }


def _fake_upload_side_effect():
    return lambda f, kind="image": {"name": Path(f).name, "subfolder": "", "type": "input"}


def _run_with(tmp_path, captured, fake_patch, preset_name="sca12_replace"):
    ref, drive = _make_ref_and_drive(tmp_path)
    # 两个 SCAIL2 preset 现在共用同一份 workflow (scail2_motion_transfer_final.json) + 同一 schema.
    # positional_args 按 user_facing_inputs 顺序: image, 362 text, 348 text, 360 text,
    #                                              469 video, 469 frame_load_cap int, 367 int, 464 int
    positional_args = (str(ref), "animal", "human", "a person walking", str(drive), 0, 81, 5)
    with patch.object(scail2_app.scail2_client, "load_workflow_template", return_value=_synthetic_workflow()), \
         patch.object(scail2_app.scail2_client, "patch_workflow", side_effect=fake_patch), \
         patch.object(scail2_app.scail2_client, "upload", side_effect=_fake_upload_side_effect()), \
         patch.object(scail2_app.scail2_client, "queue_prompt", return_value="pid-fake"), \
         patch.object(scail2_app.scail2_client, "wait_for_completion", return_value=iter(["done in 00:01"])), \
         patch.object(scail2_app.scail2_client, "get_history", return_value=_fake_history_success()), \
         patch.object(scail2_app.scail2_client, "extract_primary_video_output", return_value={"filename": "out.mp4", "subfolder": "SCAIL-2", "type": "output"}), \
         patch.object(scail2_app.scail2_client, "get_output_url", return_value="http://fake/view"):
        _collect(scail2_app.run_workflow(preset_name, *positional_args))
    return captured.get("replacements")


def test_also_patch_writes_same_drive_to_extra_node(tmp_path):
    """also_patch 列出的 node 必须拿到和主 node 同一份 drive_name。

    sca12_replace 现在用跟 sca12_motion 同一份 workflow: 主驱动在 469 (VHS_LoadVideo),
    also_patch 同步到 543 (per-iter loader)。
    """
    captured = {}
    def _fake_patch(wf, replacements, preset_config=None, validate_after=True):
        captured["replacements"] = replacements
        return wf
    reps = _run_with(tmp_path, captured, _fake_patch, "sca12_replace")
    assert reps is not None, "patch_workflow 没被调用"
    assert "469" in reps and reps["469"].get("video"), "主 node 469 没被 patch"
    assert "543" in reps and reps["543"].get("video"), "also_patch node 543 没被 patch"
    assert reps["469"]["video"] == reps["543"]["video"], "两个 node 的 video 必须是同一份"
    assert reps["469"]["video"].endswith("drive.mp4"), f"video 字段值错: {reps['469']['video']!r}"


def test_also_patch_motion_preset_also_works(tmp_path):
    """sca12_motion preset 的 also_patch 同样生效(469 主, also_patch 到 543 per-iter loader)。"""
    captured = {}
    def _fake_patch(wf, replacements, preset_config=None, validate_after=True):
        captured["replacements"] = replacements
        return wf
    reps = _run_with(tmp_path, captured, _fake_patch, "sca12_motion")
    assert reps is not None, "patch_workflow 没被调用"
    assert "469" in reps and reps["469"].get("video"), "主 node 469 没被 patch"
    assert "543" in reps and reps["543"].get("video"), "also_patch node 543 没被 patch"
    assert reps["469"]["video"] == reps["543"]["video"], "两个 node 的 video 必须是同一份"
    assert reps["469"].get("frame_load_cap") == 0, "469.frame_load_cap 没被 patch (默认 0)"
    assert reps["469"]["video"].endswith("drive.mp4")


def test_also_patch_empty_list_is_equivalent_to_no_alsopatch(tmp_path, monkeypatch):
    """also_patch: [] / 缺省时只 patch 主 node，不应报错。"""
    from app import config, scail2_app
    real = config.preset_config
    def _patched(name):
        cfg = real(name)
        if name == "sca12_replace":
            import copy
            cfg = copy.deepcopy(cfg)
            for spec in cfg["user_facing_inputs"]:
                spec.pop("also_patch", None)
        return cfg
    monkeypatch.setattr(config, "preset_config", _patched)
    monkeypatch.setattr(scail2_app, "config", config)  # run_workflow 内部从 scail2_app.config 拿
    captured = {}
    def _fake_patch(wf, replacements, preset_config=None, validate_after=True):
        captured["replacements"] = replacements
        return wf
    reps = _run_with(tmp_path, captured, _fake_patch, "sca12_replace")
    assert reps is not None
    assert "469" in reps
    assert "543" not in reps, "also_patch 缺省时不应写到 543"


def test_also_patch_does_not_lose_primary_field_when_node_id_matches(tmp_path, monkeypatch):
    """also_patch 包含主 node id 时, 不应把主字段 (field) 覆盖或丢失。

    在新 schema 下让 sca12_replace 的 also_patch 强制改成 [{node_id: '469', field: 'video'}],
    即主节点也作为镜像 target — 主节点 (469) 的 video 字段必须保留下来。
    """
    from app import config, scail2_app
    real = config.preset_config
    def _patched(name):
        cfg = real(name)
        if name == "sca12_replace":
            import copy
            cfg = copy.deepcopy(cfg)
            for spec in cfg["user_facing_inputs"]:
                if spec.get("type") == "file:video":
                    spec["also_patch"] = [{"node_id": "469", "field": "video"}]
        return cfg
    monkeypatch.setattr(config, "preset_config", _patched)
    monkeypatch.setattr(scail2_app, "config", config)
    captured = {}
    def _fake_patch(wf, replacements, preset_config=None, validate_after=True):
        captured["replacements"] = replacements
        return wf
    reps = _run_with(tmp_path, captured, _fake_patch, "sca12_replace")
    assert reps is not None
    assert "469" in reps
    assert reps["469"].get("video", "").endswith("drive.mp4")


def test_validator_does_not_inspect_also_patch_node():
    """workflow_validator 只看 user_facing_inputs 顶层 node，不校验 also_patch 列出的 node。

    边界：如果 also_patch 节点不在 workflow 里，validator 不应报错
    （also_patch 的存在性由运行时 patch_workflow 隐式创建 inputs 来保证）。
    """
    wf = _synthetic_workflow()
    del wf["469"]  # 删掉 also_patch 节点
    preset_cfg = {
        "user_facing_inputs": [
            {"node_id": "369", "field": "video", "type": "file:video", "label": "drive",
             "also_patch": [{"node_id": "469", "field": "video"}]},
            {"node_id": "30", "field": "image", "type": "file:image", "label": "ref"},
        ]
    }
    # 不应抛错
    workflow_validator.validate(wf, preset_cfg)


def test_also_patch_schema_appears_in_params_json():
    """params.json 里两个 SCAIL2 preset 必须显式声明 also_patch, 否则用户在 UI 看不出。

    两个 preset 现在共用同一份 workflow (scail2_motion_transfer_final.json) + 同一架构:
    主驱动在 469 (VHS_LoadVideo), also_patch 同步到 543 (per-iter loader)。
    不变量: 两个 node 视频必须绑同一份, 所以 also_patch 必须有 target 且 != 主节点。
    """
    import json
    p = REPO_ROOT / "app" / "presets" / "params.json"
    j = json.loads(p.read_text(encoding="utf-8"))
    for preset_name in ("sca12_replace", "sca12_motion"):
        uf = j["presets"][preset_name]["user_facing_inputs"]
        v = next((s for s in uf if s.get("type") == "file:video"), None)
        assert v is not None, f"{preset_name} 缺 file:video 项"
        assert "also_patch" in v, f"{preset_name} 的 file:video 缺 also_patch 字段"
        targets = {str(x.get("node_id")) for x in v["also_patch"]}
        primary = str(v["node_id"])
        assert targets, f"{preset_name} 的 also_patch 不能为空 (主节点 {primary} 需要一个镜像)"
        assert primary not in targets, f"{preset_name} 的 also_patch target 不该等于主节点 {primary}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))