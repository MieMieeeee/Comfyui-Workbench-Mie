"""definitions/*.json 是 preset 唯一权威源的契约测试 (workflow-decouple 2026-07-24).

锁:
  - preset_config 只从 definitions/<name>.json 读, 找不到抛 KeyError
  - list_workflows 只扫 definitions/, 不会重复也不会漏
  - save_definition 写的文件能被 preset_config 立即读到
  - 所有 preset 都必须有 definition 文件
"""
import pytest

from app import config


def test_preset_config_reads_definition_file():
    """preset_config 从 definitions/<name>.json 读 (唯一源)."""
    cfg = config.preset_config("zimage")
    assert cfg["display_name"] == "文生图 (Z-Image-Turbo)"
    assert "user_facing_inputs" in cfg


def test_list_workflows_only_scans_definitions():
    """list_workflows 只扫 definitions/, 不出现重复 preset."""
    wfs = config.list_workflows()
    names = [w["name"] for w in wfs]
    assert len(names) == len(set(names)), "有重复 preset"
    expected = {
        "zimage", "qwen_image_2512_4step", "klein_edit", "Anima_turbo",
        "sca12_motion", "sca12_replace",
        "ltx_23_t2v_distill", "ltx_23_i2v_distilled",
        "liveportrait", "sam3_mat_image", "sam3_mat_video",
        "qwen3_tts", "qwen3_tts_clone", "ace_step_15_music",
        "t2i_krea2",
    }
    assert expected == set(names), "preset 集合不对"


def test_preset_config_missing_definition_raises(tmp_path, monkeypatch):
    """definition 不存在的 preset, preset_config 抛 KeyError (不再 fallback)."""
    fake_defs = tmp_path / "definitions"
    fake_defs.mkdir()
    monkeypatch.setattr(config, "DEFINITIONS_DIR", fake_defs)
    with pytest.raises(KeyError):
        config.preset_config("nonexistent")


def test_save_definition_writes_and_is_readable(tmp_path, monkeypatch):
    """save_definition 写的文件, preset_config 能立即读到, list_workflows 也能列出."""
    fake_defs = tmp_path / "definitions"
    monkeypatch.setattr(config, "DEFINITIONS_DIR", fake_defs)
    config.save_definition("fresh", {
        "display_name": "Fresh Workflow",
        "category": "image",
        "order": 50,
        "user_facing_inputs": [],
    })
    cfg = config.preset_config("fresh")
    assert cfg["display_name"] == "Fresh Workflow"
    wfs = config.list_workflows()
    assert any(w["name"] == "fresh" for w in wfs)


def test_all_existing_presets_have_definition_files():
    """所有 preset 都必须有对应的 definition 文件 (单源, 没 definition 就不该出现)."""
    defs_dir = config.DEFINITIONS_DIR
    for w in config.list_workflows():
        def_path = defs_dir / (w["name"] + ".json")
        assert def_path.exists(), w["name"] + " 缺 definition 文件"


def test_definition_group_field_used_when_present():
    """definition 写了 group 字段, list_workflows 就应带上."""
    wfs = config.list_workflows()
    zimage = next(w for w in wfs if w["name"] == "zimage")
    assert zimage.get("group") == "图像"
    qwen3_tts = next(w for w in wfs if w["name"] == "qwen3_tts")
    assert qwen3_tts.get("group") == "音频"
