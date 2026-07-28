"""工作流向导路由测试 (/api/wizard/*).

parse + save 走完整流程 (test client). run 需要 ComfyUI, mock 掉底层调用.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import flask_app


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


# 一个最小的 ComfyUI API 格式 workflow (zimage 的简化版)
_SAMPLE_WF = {
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a prompt", "clip": ["18", 0]}, "_meta": {"title": "Positive"}},
    "13": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "3": {"class_type": "KSampler", "inputs": {"seed": 0, "cfg": 7}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "zimage"}},
}


# ============================================================
# POST /api/wizard/parse
# ============================================================

def test_wizard_parse_returns_fields_and_token(client):
    """上传 workflow JSON → 返回推断的 fields + token. 每个 field 带 confidence 字段."""
    r = client.post("/api/wizard/parse", json={"workflow_json": json.dumps(_SAMPLE_WF)})
    assert r.status_code == 200
    data = r.get_json()
    assert "token" in data
    assert "fields" in data
    assert data["node_count"] == 4
    # 应该识别出 text / seed / image_sizes
    types = {f["type"] for f in data["fields"]}
    assert "text" in types
    assert "int_random" in types  # seed
    assert "image_sizes" in types  # EmptySD3 width+height 合并
    # 每个 field 都带 confidence 字段
    for f in data["fields"]:
        assert "confidence" in f, f"field {f.get('field')} 缺 confidence"
        assert f["confidence"] in ("high", "medium", "low")
    # seed 应该是 high (高置信度, 默认勾选)
    seed_fields = [f for f in data["fields"] if f["field"] == "seed"]
    assert seed_fields[0]["confidence"] == "high"


def test_wizard_parse_missing_json_returns_400(client):
    r = client.post("/api/wizard/parse", json={})
    assert r.status_code == 400


def test_wizard_parse_invalid_json_returns_400(client):
    r = client.post("/api/wizard/parse", json={"workflow_json": "not json"})
    assert r.status_code == 400


# ============================================================
# POST /api/wizard/run (mock ComfyUI)
# ============================================================

def test_wizard_run_with_invalid_token_returns_400(client):
    r = client.post("/api/wizard/run", json={"token": "nonexistent", "fields": [], "values": {}})
    assert r.status_code == 400


def test_wizard_run_returns_outputs(client, monkeypatch):
    """run 走通: mock wizard.run_workflow_once 返回假 history → extract_all_outputs 出产物."""
    # 先 parse 拿 token
    r = client.post("/api/wizard/parse", json={"workflow_json": json.dumps(_SAMPLE_WF)})
    token = r.get_json()["token"]

    # mock 底层 ComfyUI 调用 (不真连)
    fake_history = {
        "outputs": {
            "9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]},
        }
    }
    monkeypatch.setattr(flask_app.wizard, "run_workflow_once", lambda wf, reps: fake_history)

    fields = [{"node_id": "6", "field": "text", "type": "text", "default": "x"}]
    r = client.post("/api/wizard/run", json={
        "token": token, "fields": fields, "values": {"text": "hello"},
    })
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["outputs"]) == 1
    assert data["outputs"][0]["node_id"] == "9"
    assert data["outputs"][0]["media_key"] == "images"


# ============================================================
# POST /api/wizard/save
# ============================================================

def test_wizard_save_creates_definition(client, monkeypatch, tmp_path):
    """save: 生成 definition.json + workflow 模板, 新 preset 立即可用."""
    # parse 拿 token
    r = client.post("/api/wizard/parse", json={"workflow_json": json.dumps(_SAMPLE_WF)})
    token = r.get_json()["token"]

    # redirect definitions + presets 到临时目录, 避免污染真实配置
    monkeypatch.setattr(flask_app.config, "DEFINITIONS_DIR", tmp_path / "defs")
    monkeypatch.setattr(flask_app.config, "PRESETS_DIR", tmp_path / "presets")
    (tmp_path / "presets").mkdir()
    # params.json 兜底 (list_workflows 要读)
    (tmp_path / "presets" / "params.json").write_text(
        json.dumps({"schema_version": 4, "presets": {}}), encoding="utf-8")

    fields = [{"node_id": "6", "field": "text", "type": "text", "label": "提示词", "default": "x"}]
    r = client.post("/api/wizard/save", json={
        "token": token,
        "name": "my_test_wf",
        "display_name": "测试工作流",
        "category": "image",
        "fields": fields,
        "output_node_id": "9",
        "output_kind": "image",
        "example": {"prompt": "test"},
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["name"] == "my_test_wf"

    # definition 文件已生成
    def_file = tmp_path / "defs" / "my_test_wf.json"
    assert def_file.exists()
    cfg = json.loads(def_file.read_text(encoding="utf-8"))
    assert cfg["display_name"] == "测试工作流"
    assert cfg["user_facing_inputs"] == fields
    assert cfg["output_kind"] == "image"
    # workflow 模板也存了
    assert (tmp_path / "presets" / "my_test_wf.json").exists()


def test_wizard_save_rejects_duplicate_name(client, monkeypatch, tmp_path):
    """save: 已存在的 preset 名不允许覆盖."""
    r = client.post("/api/wizard/parse", json={"workflow_json": json.dumps(_SAMPLE_WF)})
    token = r.get_json()["token"]

    # 造一个已有 preset
    defs = tmp_path / "defs"
    defs.mkdir()
    (defs / "existing.json").write_text(
        json.dumps({"display_name": "Existing", "category": "image", "order": 1}), encoding="utf-8")
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "params.json").write_text(
        json.dumps({"schema_version": 4, "presets": {}}), encoding="utf-8")
    monkeypatch.setattr(flask_app.config, "DEFINITIONS_DIR", defs)
    monkeypatch.setattr(flask_app.config, "PRESETS_DIR", presets)

    r = client.post("/api/wizard/save", json={
        "token": token, "name": "existing", "fields": [],
    })
    assert r.status_code == 409


def test_wizard_save_rejects_bad_name(client, monkeypatch, tmp_path):
    """save: 名字只能字母数字下划线."""
    r = client.post("/api/wizard/parse", json={"workflow_json": json.dumps(_SAMPLE_WF)})
    token = r.get_json()["token"]
    for bad in ["123start", "has space", "dash-name", ""]:
        r = client.post("/api/wizard/save", json={
            "token": token, "name": bad, "fields": [],
        })
        assert r.status_code == 400, f"{bad!r} 应该被拒"


def test_wizard_save_builds_example_from_selected_run_output(client, monkeypatch, tmp_path):
    r = client.post("/api/wizard/parse", json={"workflow_json": json.dumps(_SAMPLE_WF)})
    token = r.get_json()["token"]
    monkeypatch.setattr(flask_app.config, "DEFINITIONS_DIR", tmp_path / "defs")
    monkeypatch.setattr(flask_app.config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(flask_app.config, "PARAMS_FILE", tmp_path / "presets" / "params.json")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "params.json").write_text(json.dumps({"schema_version": 4, "presets": {}}), encoding="utf-8")
    expected_example = {"text": "a cat", "preview_image": "app/static/examples/new_wf.png"}
    calls = {}
    def fake_prepare(name, fields, values, output):
        calls["args"] = (name, fields, values, output)
        return expected_example
    monkeypatch.setattr(flask_app.wizard, "prepare_example", fake_prepare)
    fields = [{"node_id": "6", "field": "text", "type": "text", "default": "a cat"}]
    output = {"node_id": "9", "filename": "out.png", "subfolder": "", "type": "output", "media_key": "images"}
    r = client.post("/api/wizard/save", json={
        "token": token, "name": "new_wf", "display_name": "新工作流",
        "description": "一句用途说明", "fields": fields, "values": {"text": "a cat"},
        "selected_output": output, "output_node_id": "9", "output_kind": "image",
    })
    assert r.status_code == 200
    cfg = json.loads((tmp_path / "defs" / "new_wf.json").read_text(encoding="utf-8"))
    assert cfg["description"] == "一句用途说明"
    assert cfg["example"] == expected_example
    assert calls["args"] == ("new_wf", fields, {"text": "a cat"}, output)


def test_wizard_save_does_not_write_definition_when_preview_copy_fails(client, monkeypatch, tmp_path):
    r = client.post("/api/wizard/parse", json={"workflow_json": json.dumps(_SAMPLE_WF)})
    token = r.get_json()["token"]
    monkeypatch.setattr(flask_app.config, "DEFINITIONS_DIR", tmp_path / "defs")
    monkeypatch.setattr(flask_app.config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(flask_app.config, "PARAMS_FILE", tmp_path / "presets" / "params.json")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "params.json").write_text(json.dumps({"schema_version": 4, "presets": {}}), encoding="utf-8")
    monkeypatch.setattr(flask_app.wizard, "prepare_example", lambda *args: (_ for _ in ()).throw(FileNotFoundError("missing output")))
    r = client.post("/api/wizard/save", json={"token": token, "name": "broken_wf", "fields": [], "selected_output": {"filename": "missing.png"}})
    assert r.status_code == 422
    assert not (tmp_path / "defs" / "broken_wf.json").exists()


# ============================================================
# PUT /api/wizard/preset-order (工作流顺序调整)
# ============================================================

def test_preset_order_rewrites_params_orders(client, monkeypatch, tmp_path):
    """按新顺序调整工作流 → params.json 里的 order 字段被重写, 步长 10."""
    monkeypatch.setattr(flask_app.config, "DEFINITIONS_DIR", tmp_path / "defs")
    monkeypatch.setattr(flask_app.config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(flask_app.config, "PARAMS_FILE", tmp_path / "presets" / "params.json")
    (tmp_path / "presets").mkdir()
    params = {
        "schema_version": 4,
        "presets": {
            "a": {"display_name": "A", "category": "image", "order": 10},
            "b": {"display_name": "B", "category": "image", "order": 20},
            "c": {"display_name": "C", "category": "image", "order": 30},
        },
    }
    (tmp_path / "presets" / "params.json").write_text(json.dumps(params), encoding="utf-8")

    r = client.put("/api/wizard/preset-order", json={"order": ["c", "a", "b"]})
    assert r.status_code == 200
    data = r.get_json()
    assert [row["name"] for row in data["order"]] == ["c", "a", "b"]
    assert [row["order"] for row in data["order"]] == [10, 20, 30]

    after = json.loads((tmp_path / "presets" / "params.json").read_text(encoding="utf-8"))
    assert after["presets"]["a"]["order"] == 20
    assert after["presets"]["b"]["order"] == 30
    assert after["presets"]["c"]["order"] == 10


def test_preset_order_writes_definition_when_present(client, monkeypatch, tmp_path):
    """在 definitions/ 里的 preset → order 写到 definition 文件, 不动 params.json (除了 key 不存在的)."""
    defs = tmp_path / "defs"
    defs.mkdir()
    (defs / "newly_added.json").write_text(
        json.dumps({"display_name": "Newly Added", "category": "image", "order": 999}),
        encoding="utf-8",
    )
    monkeypatch.setattr(flask_app.config, "DEFINITIONS_DIR", defs)
    monkeypatch.setattr(flask_app.config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(flask_app.config, "PARAMS_FILE", tmp_path / "presets" / "params.json")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "params.json").write_text(
        json.dumps({"schema_version": 4, "presets": {}}, ensure_ascii=False), encoding="utf-8"
    )

    r = client.put("/api/wizard/preset-order", json={"order": ["newly_added"]})
    assert r.status_code == 200
    after = json.loads((defs / "newly_added.json").read_text(encoding="utf-8"))
    assert after["order"] == 10
    # params.json 没多出这个 key
    params_after = json.loads((tmp_path / "presets" / "params.json").read_text(encoding="utf-8"))
    assert "newly_added" not in params_after.get("presets", {})


def test_preset_order_rejects_unknown_name(client, monkeypatch, tmp_path):
    monkeypatch.setattr(flask_app.config, "DEFINITIONS_DIR", tmp_path / "defs")
    monkeypatch.setattr(flask_app.config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(flask_app.config, "PARAMS_FILE", tmp_path / "presets" / "params.json")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "params.json").write_text(
        json.dumps({"schema_version": 4, "presets": {"a": {"display_name": "A", "order": 10}}}),
        encoding="utf-8",
    )
    r = client.put("/api/wizard/preset-order", json={"order": ["a", "ghost"]})
    assert r.status_code == 400
    assert "ghost" in r.get_json()["error"]


def test_preset_order_rejects_duplicates(client, monkeypatch, tmp_path):
    monkeypatch.setattr(flask_app.config, "DEFINITIONS_DIR", tmp_path / "defs")
    monkeypatch.setattr(flask_app.config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(flask_app.config, "PARAMS_FILE", tmp_path / "presets" / "params.json")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "params.json").write_text(
        json.dumps({"schema_version": 4, "presets": {"a": {"display_name": "A", "order": 10}}}),
        encoding="utf-8",
    )
    r = client.put("/api/wizard/preset-order", json={"order": ["a", "a"]})
    assert r.status_code == 400


def test_preset_order_rejects_empty(client, monkeypatch, tmp_path):
    monkeypatch.setattr(flask_app.config, "DEFINITIONS_DIR", tmp_path / "defs")
    monkeypatch.setattr(flask_app.config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(flask_app.config, "PARAMS_FILE", tmp_path / "presets" / "params.json")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "params.json").write_text(
        json.dumps({"schema_version": 4, "presets": {"a": {"display_name": "A", "order": 10}}}),
        encoding="utf-8",
    )
    r = client.put("/api/wizard/preset-order", json={"order": []})
    assert r.status_code == 400


def test_preset_order_refuses_subset(client, monkeypatch, tmp_path):
    """order 必须是完整列表, 不能只送一部分 (避免误操作覆盖未提交的 preset)."""
    monkeypatch.setattr(flask_app.config, "DEFINITIONS_DIR", tmp_path / "defs")
    monkeypatch.setattr(flask_app.config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(flask_app.config, "PARAMS_FILE", tmp_path / "presets" / "params.json")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "params.json").write_text(
        json.dumps({"schema_version": 4, "presets": {
            "a": {"display_name": "A", "order": 10},
            "b": {"display_name": "B", "order": 20},
        }}),
        encoding="utf-8",
    )
    r = client.put("/api/wizard/preset-order", json={"order": ["a"]})
    assert r.status_code == 400
    assert "ghost" not in r.get_json()["error"]  # 应该是 "未知 preset: ['b']" 之类的
