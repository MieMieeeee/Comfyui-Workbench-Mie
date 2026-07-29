"""已有工作流输入布局编辑：安全重排 definition.user_facing_inputs。"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Iterable

from app import config

# 保存排序时给每个 preset 分配的 order 步长. 现有 preset 的 order 是
# 10, 20, ..., 210 (步长 10), 留空间让以后插入新 preset 不用重排老的.
_ORDER_STEP = 10
_ORDER_BASE = 10


EDITABLE_FIELDS = ("label", "tier", "help")


def stable_input_id(spec: dict) -> str:
    return f"{spec.get('node_id')}::{spec.get('field')}"


def _definition_path(name: str) -> Path:
    return config.DEFINITIONS_DIR / f"{name}.json"


def _layout_path(name: str) -> Path:
    return config.INPUT_LAYOUTS_DIR / f"{name}.json"


def _source_info(name: str) -> tuple[str, bool]:
    """检查 preset 的 definition 文件 + 是否存在用户布局.

    单源后所有 preset 都在 definitions/, source 永远是 "definition".
    保留 builtin 分支以兼容 wizard 模板里写死的标签.
    """
    has_definition = _definition_path(name).is_file()
    if not has_definition:
        raise KeyError(f"unknown preset: {name} (no definition at {_definition_path(name)})")
    return "definition", _layout_path(name).is_file()


# group 字段: 把 category 映射到中文显示组, 跟 wizard 调整顺序 tab 的 5 个固定组对齐.
# 缺省时按 category 推 (image→图像, video→视频, audio→音频, 其它→其它), 用户在
# wizard 里改 group 后写到 definition 文件, 后续优先用文件里的值.
_GROUP_BY_CATEGORY = {
    "image": "图像",
    "video": "视频",
    "audio": "音频",
    "other": "其他",
    # "通用" 不从 category 推, 必须用户主动设
}
# 组的固定顺序 (wizard 调整顺序 tab 渲染用)
_GROUP_ORDER = ("图像", "视频", "音频", "通用", "其他")


def _workflow_group(name: str, row: dict) -> str:
    """读 preset 的 group, 缺省从 category 推."""
    cfg = config.preset_config(name) if hasattr(config, "preset_config") else None
    if cfg and cfg.get("group"):
        return cfg["group"]
    cat = row.get("category", "other")
    return _GROUP_BY_CATEGORY.get(cat, "其他")


def list_editable_workflows() -> list[dict]:
    rows = []
    for row in config.list_workflows():
        source, can_restore = _source_info(row["name"])
        grp = _workflow_group(row["name"], row)
        rows.append({**row, "source": source, "can_restore": can_restore, "group": grp})
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
    # 保留原文件的行尾 (LF / CRLF). 仓库里 definition 文件两种行尾都有, 一律写 LF
    # 会让 CRLF 的文件整文件重写 (git diff 看着几百行改了实际只改了 1 行 + 行尾).
    # 注: json.dumps 总是产出 LF, 直接 append newline 只影响最后一处; 整文要替换.
    path.parent.mkdir(parents=True, exist_ok=True)
    use_crlf = False
    if path.is_file():
        with open(path, "rb") as f:
            sample = f.read(4096)
        if b"\r\n" in sample and sample.count(b"\r\n") > sample.count(b"\n") - sample.count(b"\r\n"):
            use_crlf = True
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if use_crlf:
        text = text.replace("\n", "\r\n")
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8", newline="") as f:
        f.write(text + ("\r\n" if use_crlf else "\n"))
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


def _set_definition_order(name: str, order: int) -> bool:
    """把 order 写进 definition 文件. 返回 True 表示有定义并写入."""
    def_path = _definition_path(name)
    if not def_path.is_file():
        return False
    try:
        cfg = json.loads(def_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(cfg, dict):
        return False
    cfg["order"] = order
    _atomic_write_json(def_path, cfg)
    return True


def _set_definition_group(name: str, group: str) -> bool:
    """把 group 写进 definition 文件. 返回 True 表示有定义并写入."""
    def_path = _definition_path(name)
    if not def_path.is_file():
        return False
    try:
        cfg = json.loads(def_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(cfg, dict):
        return False
    cfg["group"] = group
    _atomic_write_json(def_path, cfg)
    return True


def save_preset_order(ordered_items: Iterable) -> dict:
    """保存工作流的顺序 + 分组.

    入参是 list[{name, group}], 顺序按 list 里的位置决定. 每个 preset 拿步长 10
    分配 order (跟历史一致, 留插入空间); 跟原 group 不同时写 definition 文件.
    写回 definition 文件 (单源, 没有 params.json 兜底).

    向后兼容: 旧前端如果传 list[str] (只有 name), group 走缺省 (按 category 推),
    行为跟 review 2026-07-28 那笔一致.
    """
    if not isinstance(ordered_items, (list, tuple)):
        raise ValueError("order 必须是数组, 不能为空 / 重复 / 包含未知 preset")
    # 归一化: 接受 list[str] (老格式) 或 list[{name, group}] (新格式)
    normalized: list[dict] = []
    for it in ordered_items:
        if isinstance(it, str):
            normalized.append({"name": it, "group": None})
        elif isinstance(it, dict) and isinstance(it.get("name"), str):
            normalized.append({"name": it["name"], "group": it.get("group")})
        else:
            raise ValueError("order 元素必须是字符串 name 或 {name, group} dict")
    if not normalized or len({n["name"] for n in normalized}) != len(normalized):
        raise ValueError("order 必须是数组, 不能为空 / 重复 / 包含未知 preset")
    known = {row["name"] for row in config.list_workflows()}
    missing = [n["name"] for n in normalized if n["name"] not in known]
    if missing:
        raise ValueError(f"未知 preset: {missing}. 已知: {sorted(known)}")
    # 必须传完整列表: 不在提交里的 preset 也算缺失, 避免误操作把剩下的 order/group 漏更新
    not_in_request = sorted(known - {n["name"] for n in normalized})
    if not_in_request:
        raise ValueError(
            f"order 必须包含所有 preset, 漏了: {not_in_request}. 完整列表: {sorted(known)}"
        )
    # group 必须是 _GROUP_ORDER 里的合法值
    valid_groups = set(_GROUP_ORDER)
    result = []
    for idx, item in enumerate(normalized):
        name = item["name"]
        new_order = _ORDER_BASE + idx * _ORDER_STEP
        # 写 order (单源: definition)
        if not _set_definition_order(name, new_order):
            raise ValueError(f"preset {name} 没有 definition 文件, 无法写 order")
        # 写 group: 缺省 None 跳过 (保持原 group, 让 _workflow_group 继续从 category 推)
        new_group = item.get("group")
        if new_group is not None:
            if new_group not in valid_groups:
                raise ValueError(f"未知 group: {new_group!r}. 合法: {list(_GROUP_ORDER)}")
            if not _set_definition_group(name, new_group):
                raise ValueError(f"preset {name} 没有 definition 文件, 无法写 group")
        result.append({"name": name, "order": new_order, "group": new_group})
    return {"order": result}
