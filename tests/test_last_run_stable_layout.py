"""last_run 使用 stable input id，输入重排后仍映射到正确字段。"""
import json

from app import config
from app.services import persistence


SPECS = [
    {"node_id": "1", "field": "text", "type": "text", "default": "default"},
    {"node_id": "6", "field": "width", "type": "int", "default": 1024},
    {"node_id": "6", "field": "height", "type": "int", "default": 768},
    {"node_id": "9", "field": "seed", "type": "int_random", "default": 0},
]


def test_save_last_run_writes_stable_id_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    persistence._save_last_run("demo", ["hello", 1280, 720, False, 42], SPECS)
    data = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert data == {
        "schema_version": 2,
        "values_by_input": {
            "1::text": "hello", "6::width": 1280, "6::height": 720,
            "9::seed": {"random": False, "value": 42},
        },
    }


def test_load_last_run_follows_current_reordered_specs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    persistence._save_last_run("demo", ["hello", 1280, 720, False, 42], SPECS)
    reordered = [SPECS[3], SPECS[2], SPECS[0], SPECS[1]]
    assert persistence._load_last_run("demo", reordered) == [False, 42, 720, "hello", 1280]


def test_load_last_run_defaults_missing_stable_values(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    (tmp_path / "demo.json").write_text(json.dumps({"schema_version": 2, "values_by_input": {"1::text": "saved"}}), encoding="utf-8")
    assert persistence._load_last_run("demo", SPECS) == ["saved", 1024, 768, True, 0]


def test_load_last_run_keeps_legacy_list_compatibility(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    (tmp_path / "demo.json").write_text(json.dumps(["old", 640, 480, True, 99]), encoding="utf-8")
    assert persistence._load_last_run("demo", SPECS) == ["old", 640, 480, True, 99]
