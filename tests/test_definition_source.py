"""definition 文件作为 preset 主源的契约测试 (workflow-decouple 2026-07-24).

锁:
  - preset_config 优先读 definitions/<name>.json, 找不到才回退 params.json
  - list_workflows 合并两源, 同名不重复 (definition 覆盖 params.json)
  - save_definition 写的文件能被 preset_config 立即读到
"""
import json

from app import config


def test_preset_config_reads_definition_file():
    """preset_config 应该从 definitions/<name>.json 读取 (主源)."""
    cfg = config.preset_config("zimage")
    assert cfg["display_name"] == "文生图 (Z-Image-Turbo)"
    assert "user_facing_inputs" in cfg


def test_list_workflows_merges_both_sources_no_duplicates():
    """list_workflows 合并 definitions/ + params.json, 同名不重复."""
    wfs = config.list_workflows()
    names = [w["name"] for w in wfs]
    # 没有重复
    assert len(names) == len(set(names)), f"有重复 preset: {names}"
    # 已知的 10 个都在
    expected = {
        "zimage", "qwen_image_2512_4step", "klein_edit",
        "sca12_motion", "sca12_replace",
        "ltx_23_t2v_distill", "ltx_23_i2v_distilled",
        "liveportrait", "qwen3_tts", "ace_step_15_music",
    }
    assert expected.issubset(set(names)), f"缺 preset: {expected - set(names)}"


def test_definition_overrides_params_json(tmp_path, monkeypatch):
    """同名 preset, definition 文件覆盖 params.json (新源优先)."""
    # 构造一个 fake params.json + definitions/ 目录
    fake_presets = tmp_path / "presets"
    fake_presets.mkdir()
    # params.json 里有 "dup" preset (旧值)
    (fake_presets / "params.json").write_text(
        json.dumps({"schema_version": 4, "presets": {
            "dup": {"display_name": "OLD", "category": "other", "order": 1}
        }}), encoding="utf-8")
    # definitions/dup.json 有同名 (新值, 应覆盖)
    defs = fake_presets / "definitions"
    defs.mkdir()
    (defs / "dup.json").write_text(
        json.dumps({"display_name": "NEW", "category": "image", "order": 1}), encoding="utf-8")

    monkeypatch.setattr(config, "PRESETS_DIR", fake_presets)
    monkeypatch.setattr(config, "PARAMS_FILE", fake_presets / "params.json")
    monkeypatch.setattr(config, "DEFINITIONS_DIR", defs)

    cfg = config.preset_config("dup")
    assert cfg["display_name"] == "NEW", "definition 应覆盖 params.json"


def test_preset_config_falls_back_to_params_json(tmp_path, monkeypatch):
    """definition 不存在的 preset, 回退读 params.json (迁移期兼容)."""
    fake_presets = tmp_path / "presets"
    fake_presets.mkdir()
    (fake_presets / "params.json").write_text(
        json.dumps({"schema_version": 4, "presets": {
            "legacy": {"display_name": "Legacy", "category": "other", "order": 1}
        }}), encoding="utf-8")
    defs = fake_presets / "definitions"
    defs.mkdir()  # 空, 没有 legacy.json

    monkeypatch.setattr(config, "PRESETS_DIR", fake_presets)
    monkeypatch.setattr(config, "PARAMS_FILE", fake_presets / "params.json")
    monkeypatch.setattr(config, "DEFINITIONS_DIR", defs)

    cfg = config.preset_config("legacy")
    assert cfg["display_name"] == "Legacy"


def test_save_definition_writes_and_is_readable(tmp_path, monkeypatch):
    """save_definition 写的文件, preset_config 能立即读到."""
    fake_presets = tmp_path / "presets"
    fake_presets.mkdir()
    (fake_presets / "params.json").write_text(
        json.dumps({"schema_version": 4, "presets": {}}), encoding="utf-8")
    defs = fake_presets / "definitions"

    monkeypatch.setattr(config, "PRESETS_DIR", fake_presets)
    monkeypatch.setattr(config, "PARAMS_FILE", fake_presets / "params.json")
    monkeypatch.setattr(config, "DEFINITIONS_DIR", defs)

    config.save_definition("fresh", {
        "display_name": "Fresh Workflow",
        "category": "image",
        "order": 50,
        "user_facing_inputs": [],
    })
    # 立即可读
    cfg = config.preset_config("fresh")
    assert cfg["display_name"] == "Fresh Workflow"
    # list_workflows 也能列出来
    wfs = config.list_workflows()
    assert any(w["name"] == "fresh" for w in wfs)


def test_all_existing_presets_have_definition_files():
    """迁移后, 所有 preset 都应该有对应的 definition 文件."""
    defs_dir = config.DEFINITIONS_DIR
    for w in config.list_workflows():
        def_path = defs_dir / f"{w['name']}.json"
        assert def_path.exists(), f"{w['name']} 缺 definition 文件: {def_path}"
