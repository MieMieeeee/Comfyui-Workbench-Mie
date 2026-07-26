"""表单状态持久化：stable-id v2 + 旧位置列表兼容。"""
from __future__ import annotations

import json
import logging

from app import config

_log = logging.getLogger("app.services.persistence")


def _safe_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, dict)):
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            pass
    try:
        return str(value)
    except Exception:
        return None


def _stable_id(spec: dict) -> str:
    return f"{spec.get('node_id')}::{spec.get('field')}"


def _default_flat_values(specs: list[dict], missing=None) -> list:
    out = []
    for spec in specs:
        if spec.get("type") == "int_random":
            out.extend([bool(spec.get("random_default", True)), spec.get("default", 0)])
        else:
            out.append(spec.get("default", missing))
    return out


def _save_last_run(preset_name, values, specs=None):
    """保存上次成功参数；传 specs 时写 stable-id v2，未传时兼容旧列表。"""
    try:
        safe = [_safe_value(v) for v in values]
        if specs is None:
            payload = safe
        else:
            mapped = {}
            idx = 0
            for spec in specs:
                sid = _stable_id(spec)
                if spec.get("type") == "int_random":
                    mapped[sid] = {
                        "random": bool(safe[idx]) if idx < len(safe) else bool(spec.get("random_default", True)),
                        "value": safe[idx + 1] if idx + 1 < len(safe) else spec.get("default", 0),
                    }
                    idx += 2
                else:
                    mapped[sid] = safe[idx] if idx < len(safe) else spec.get("default")
                    idx += 1
            payload = {"schema_version": 2, "values_by_input": mapped}
        config.LAST_RUN_DIR.mkdir(parents=True, exist_ok=True)
        (config.LAST_RUN_DIR / f"{preset_name}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        _log.warning(f"[last_run] save failed for {preset_name}: {e}")


def _load_last_run(preset_name, specs_or_count):
    """按当前 specs 展开 v2；旧 list 文件与旧 count 调用保持兼容。"""
    specs = specs_or_count if isinstance(specs_or_count, list) else None
    count = len(_default_flat_values(specs, None)) if specs is not None else int(specs_or_count)
    fallback = _default_flat_values(specs, None) if specs is not None else [None] * count
    path = config.LAST_RUN_DIR / f"{preset_name}.json"
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return (data + [None] * count)[:count]
        if not specs or not isinstance(data, dict) or data.get("schema_version") != 2:
            return fallback
        mapped = data.get("values_by_input", {})
        out = []
        for spec in specs:
            value = mapped.get(_stable_id(spec))
            if spec.get("type") == "int_random":
                if isinstance(value, dict):
                    out.extend([bool(value.get("random")), value.get("value", spec.get("default", 0))])
                else:
                    out.extend([bool(spec.get("random_default", True)), spec.get("default", 0)])
            else:
                out.append(spec.get("default") if value is None else value)
        return out
    except Exception:
        return fallback
