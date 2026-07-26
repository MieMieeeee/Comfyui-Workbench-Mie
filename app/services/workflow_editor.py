"""已有工作流输入布局编辑：安全重排 definition.user_facing_inputs。"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from app import config


EDITABLE_FIELDS = ("label", "tier", "help")


def stable_input_id(spec: dict) -> str:
    return f"{spec.get('node_id')}::{spec.get('field')}"


def _builtin_presets() -> dict[str, dict]:
    try:
        raw = json.loads(config.PARAMS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return raw.get("presets", {}) if isinstance(raw, dict) else {}


def _definition_path(name: str) -> Path:
    return config.DEFINITIONS_DIR / f"{name}.json"


def _layout_path(name: str) -> Path:
    return config.INPUT_LAYOUTS_DIR / f"{name}.json"


def _source_info(name: str) -> tuple[str, bool]:
    builtin = name in _builtin_presets()
    has_definition = _definition_path(name).is_file()
    if not builtin and not has_definition:
        raise KeyError(f"unknown preset: {name}")
    source = "definition" if has_definition else "builtin"
    return source, _layout_path(name).is_file()


def list_editable_workflows() -> list[dict]:
    rows = []
    for row in config.list_workflows():
        source, can_restore = _source_info(row["name"])
        rows.append({**row, "source": source, "can_restore": can_restore})
    return rows


def get_editor_definition(name: str) -> dict:
    cfg = config.preset_config(name)
    source, can_restore = _source_info(name)
    inputs = []
    for spec in cfg.get("user_facing_inputs", []):
        inputs.append({
            "stable_id": stable_input_id(spec),
            "node_id": str(spec.get("node_id")),
            "field": spec.get("field"),
            "type": spec.get("type"),
            "label": spec.get("label", spec.get("field", "")),
            "tier": spec.get("tier", "basic"),
            "help": spec.get("help", ""),
        })
    return {
        "name": name,
        "display_name": cfg.get("display_name", name),
        "source": source,
        "can_restore": can_restore,
        "inputs": inputs,
    }


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def save_input_layout(name: str, submitted: list[dict]) -> dict:
    if not isinstance(submitted, list):
        raise ValueError("输入项必须是数组")
    cfg = copy.deepcopy(config.preset_config(name))
    original = cfg.get("user_facing_inputs", [])
    by_id = {stable_input_id(spec): spec for spec in original}
    ids = [item.get("stable_id") for item in submitted if isinstance(item, dict)]
    if len(ids) != len(original) or len(set(ids)) != len(ids) or set(ids) != set(by_id):
        raise ValueError("输入项必须与当前配置一一对应，不能缺失、重复或新增")

    reordered = []
    for item in submitted:
        spec = copy.deepcopy(by_id[item["stable_id"]])
        for key in EDITABLE_FIELDS:
            if key in item:
                value = item[key]
                if key == "tier" and value not in ("basic", "advanced"):
                    raise ValueError("输入项 tier 只能是 basic 或 advanced")
                if not isinstance(value, str):
                    raise ValueError(f"输入项 {key} 必须是字符串")
                spec[key] = value.strip()
        reordered.append(spec)
    layout = {"schema_version": 1, "inputs": []}
    for spec in reordered:
        layout["inputs"].append({
            "stable_id": stable_input_id(spec),
            "label": spec.get("label", ""),
            "tier": spec.get("tier", "basic"),
            "help": spec.get("help", ""),
        })
    _atomic_write_json(_layout_path(name), layout)
    source, can_restore = _source_info(name)
    return {"name": name, "source": source, "can_restore": can_restore, "inputs": get_editor_definition(name)["inputs"]}


def restore_input_layout(name: str) -> bool:
    _source_info(name)
    path = _layout_path(name)
    if path.exists():
        path.unlink()
        return True
    return False
