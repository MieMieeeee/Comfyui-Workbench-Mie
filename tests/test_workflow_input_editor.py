"""已有工作流输入编辑器：内置 override 与自定义 definition 均可安全重排。"""
import json

import pytest

from app import config
from app.services import workflow_editor


def _spec(node, field, label, **extra):
    return {"node_id": str(node), "field": field, "type": extra.pop("type", "text"), "label": label, **extra}


@pytest.fixture
def sources(tmp_path, monkeypatch):
    presets = tmp_path / "presets"
    defs = presets / "definitions"
    defs.mkdir(parents=True)
    builtin = {
        "workflow_file": "builtin.json", "display_name": "内置流程",
        "category": "image", "order": 1, "description": "builtin",
        "user_facing_inputs": [
            _spec(1, "text", "提示词", default="x", help="old"),
            _spec(6, "width", "宽度", type="int", default=1024),
            _spec(6, "height", "高度", type="int", default=1024),
        ],
        "example": {"text": "x"}, "output_kind": "image",
    }
    custom = {
        "workflow_file": "custom.json", "display_name": "自定义流程",
        "category": "video", "order": 2, "description": "custom",
        "user_facing_inputs": [
            _spec(20, "video", "视频", type="file:video", default="demo.mp4"),
            _spec(21, "seed", "种子", type="int_random", default=7, random_default=True),
        ],
        "example": {"drive_video": "demo.mp4", "seed": 7}, "output_kind": "video",
    }
    # 单源: builtin + custom 都写到 definitions/, 不再有 params.json
    (defs / "builtin.json").write_text(json.dumps(builtin), encoding="utf-8")
    (defs / "custom.json").write_text(json.dumps(custom), encoding="utf-8")
    monkeypatch.setattr(config, "PRESETS_DIR", presets)
    monkeypatch.setattr(config, "DEFINITIONS_DIR", defs)
    monkeypatch.setattr(config, "INPUT_LAYOUTS_DIR", tmp_path / "input_layouts")
    return presets, defs, builtin, custom


def test_list_editable_workflows_includes_builtin_and_custom(sources):
    rows = workflow_editor.list_editable_workflows()
    assert [(r["name"], r["source"], r["can_restore"]) for r in rows] == [
        ("builtin", "definition", False), ("custom", "definition", False),
    ]


def test_get_editor_definition_exposes_stable_ids(sources):
    data = workflow_editor.get_editor_definition("builtin")
    assert [i["stable_id"] for i in data["inputs"]] == ["1::text", "6::width", "6::height"]
    assert data["source"] == "definition"


def test_save_builtin_creates_layout_override(sources):
    _presets, defs, builtin, _custom = sources
    payload = [
        {"stable_id": "6::height", "label": "画布高度", "tier": "advanced", "help": "高度说明"},
        {"stable_id": "1::text", "label": "画面描述", "tier": "basic", "help": "提示说明"},
        {"stable_id": "6::width", "label": "画布宽度", "tier": "basic", "help": "宽度说明"},
    ]
    result = workflow_editor.save_input_layout("builtin", payload)
    layout = json.loads((config.INPUT_LAYOUTS_DIR / "builtin.json").read_text(encoding="utf-8"))
    assert result["can_restore"] is True
    assert (defs / "builtin.json").exists()  # 单源后 builtin 也在 definitions/
    assert [x["stable_id"] for x in layout["inputs"]] == ["6::height", "1::text", "6::width"]
    effective = config.preset_config("builtin")
    assert effective["workflow_file"] == builtin["workflow_file"]
    assert effective["example"] == builtin["example"]
    assert effective["user_facing_inputs"][0]["default"] == 1024
    assert effective["user_facing_inputs"][0]["label"] == "画布高度"


def test_save_custom_uses_layout_override_without_rewriting_definition(sources):
    _presets, defs, _builtin, custom = sources
    payload = [
        {"stable_id": "21::seed", "label": "随机种子", "tier": "advanced", "help": "固定可复现"},
        {"stable_id": "20::video", "label": "驱动视频", "tier": "basic", "help": "上传视频"},
    ]
    workflow_editor.save_input_layout("custom", payload)
    saved = json.loads((defs / "custom.json").read_text(encoding="utf-8"))
    assert saved == custom
    effective = config.preset_config("custom")
    assert effective["example"] == custom["example"]
    assert effective["user_facing_inputs"][0]["random_default"] is True
    assert effective["user_facing_inputs"][0]["tier"] == "advanced"


@pytest.mark.parametrize("payload", [
    [{"stable_id": "1::text"}, {"stable_id": "6::width"}],
    [{"stable_id": "1::text"}, {"stable_id": "1::text"}, {"stable_id": "6::height"}],
    [{"stable_id": "1::text"}, {"stable_id": "6::width"}, {"stable_id": "999::ghost"}],
])
def test_save_rejects_missing_duplicate_or_unknown_inputs(sources, payload):
    with pytest.raises(ValueError, match="输入项"):
        workflow_editor.save_input_layout("builtin", payload)


def test_restore_builtin_removes_override_and_returns_original_order(sources):
    _presets, defs, _builtin, _custom = sources
    workflow_editor.save_input_layout("builtin", [
        {"stable_id": "6::height"}, {"stable_id": "6::width"}, {"stable_id": "1::text"},
    ])
    assert (config.INPUT_LAYOUTS_DIR / "builtin.json").exists()
    assert workflow_editor.restore_input_layout("builtin") is True
    assert not (config.INPUT_LAYOUTS_DIR / "builtin.json").exists()
    assert [x["field"] for x in config.preset_config("builtin")["user_facing_inputs"]] == ["text", "width", "height"]


def test_restore_custom_removes_only_layout_override(sources):
    _presets, defs, _builtin, custom = sources
    workflow_editor.save_input_layout("custom", [{"stable_id": "21::seed"}, {"stable_id": "20::video"}])
    assert workflow_editor.restore_input_layout("custom") is True
    assert json.loads((defs / "custom.json").read_text(encoding="utf-8")) == custom


@pytest.fixture
def client(sources):
    from app import flask_app
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_editor_routes_list_and_read_both_sources(client):
    listed = client.get("/api/wizard/editable-workflows")
    assert listed.status_code == 200
    assert {x["name"] for x in listed.get_json()} == {"builtin", "custom"}
    assert client.get("/api/wizard/definition/builtin").get_json()["source"] == "definition"  # 单源后所有 preset 都来自 definition
    assert client.get("/api/wizard/definition/custom").get_json()["source"] == "definition"


def test_editor_route_saves_reordered_layout(client):
    payload = {"inputs": [
        {"stable_id": "6::height", "label": "高度", "tier": "basic", "help": ""},
        {"stable_id": "6::width", "label": "宽度", "tier": "basic", "help": ""},
        {"stable_id": "1::text", "label": "提示", "tier": "advanced", "help": "说明"},
    ]}
    r = client.put("/api/wizard/definition/builtin/inputs", json=payload)
    assert r.status_code == 200
    assert [x["stable_id"] for x in r.get_json()["inputs"]] == ["6::height", "6::width", "1::text"]


def test_editor_route_rejects_invalid_payload_and_unknown(client):
    assert client.put("/api/wizard/definition/builtin/inputs", json={"inputs": []}).status_code == 400
    assert client.get("/api/wizard/definition/missing").status_code == 404


def test_editor_restore_route_restores_layout_override(client):
    payload = {"inputs": [
        {"stable_id": "6::height"}, {"stable_id": "6::width"}, {"stable_id": "1::text"},
    ]}
    assert client.put("/api/wizard/definition/builtin/inputs", json=payload).status_code == 200
    restored = client.delete("/api/wizard/definition/builtin/override")
    assert restored.status_code == 200
    assert restored.get_json()["restored"] is True
    assert client.delete("/api/wizard/definition/custom/override").status_code == 200


def test_invalid_or_stale_layout_is_ignored(sources):
    config.INPUT_LAYOUTS_DIR.mkdir(parents=True)
    layout = config.INPUT_LAYOUTS_DIR / "builtin.json"
    layout.write_text("not json", encoding="utf-8")
    assert [x["field"] for x in config.preset_config("builtin")["user_facing_inputs"]] == ["text", "width", "height"]
    layout.write_text(json.dumps({"schema_version": 1, "inputs": [{"stable_id": "1::text"}]}), encoding="utf-8")
    assert [x["field"] for x in config.preset_config("builtin")["user_facing_inputs"]] == ["text", "width", "height"]


def test_layout_cannot_change_runtime_type_or_default(sources):
    workflow_editor.save_input_layout("builtin", [
        {"stable_id": "6::width", "type": "file:video", "default": 1},
        {"stable_id": "1::text", "type": "bool", "default": False},
        {"stable_id": "6::height", "type": "text", "default": "bad"},
    ])
    specs = config.preset_config("builtin")["user_facing_inputs"]
    assert [(x["field"], x["type"], x["default"]) for x in specs] == [
        ("width", "int", 1024), ("text", "text", "x"), ("height", "int", 1024),
    ]
