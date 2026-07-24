"""表单状态持久化 — last_run 的保存/加载.

依赖: app.config.LAST_RUN_DIR

注: theme 持久化 (_save_theme / _load_saved_theme) 放在 theme.py,
因为 _load_saved_theme 调用 _list_themes, 逻辑上属于主题管理.
"""
from __future__ import annotations

import json
import logging

from app import config

_log = logging.getLogger("app.services.persistence")


def _save_last_run(preset_name, values):
    """跑成功时把当前表单值写到 app/data/last_run/{preset_name}.json。

    与 app/data/runs/ 的 audit manifest 不重叠:manifest 是完整的运行记录,
    这里只存"上次成功跑的参数",给 UI 的"加载上次成功参数"按钮用,失败不写。

    values: 表单值的列表 (None / str / int / float / bool / list / dict).
    非 JSON-native 的值会被序列化成 str.
    """
    try:
        safe = []
        for v in values:
            if v is None:
                safe.append(None)
            elif isinstance(v, (str, int, float, bool)):
                safe.append(v)
            elif isinstance(v, (list, tuple, dict)):
                try:
                    json.dumps(v)
                    safe.append(v)
                except (TypeError, ValueError):
                    safe.append(str(v))
            else:
                try:
                    safe.append(str(v))
                except Exception:
                    safe.append(None)
        config.LAST_RUN_DIR.mkdir(parents=True, exist_ok=True)
        path = config.LAST_RUN_DIR / f"{preset_name}.json"
        path.write_text(json.dumps(safe, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        _log.warning(f"[last_run] save failed for {preset_name}: {e}")


def _load_last_run(preset_name, n_inputs):
    """读 last_run,没有就返回全 None 列表。读坏也返 None(不崩)。"""
    path = config.LAST_RUN_DIR / f"{preset_name}.json"
    if not path.exists():
        return [None] * n_inputs
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return [None] * n_inputs
        if len(data) < n_inputs:
            data = data + [None] * (n_inputs - len(data))
        return data[:n_inputs]
    except Exception:
        return [None] * n_inputs
