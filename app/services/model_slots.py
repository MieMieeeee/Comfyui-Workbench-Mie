"""模型参数类支持:发现 loader 节点 + 从 ComfyUI /object_info 取本机已装模型列表。

「模型」是 user_facing_inputs 里 type="model"/tier="model" 的条目 —— 一个动态下拉:
选项来自本机 /object_info, 默认值是工作流自带的模型文件名 (spec.default), 用户可二次
选择覆盖成自己装的同类型模型. 持久化/patch 复用 user_facing_inputs 现有链路, 本模块
只负责「列出槽位 + 给本机已装选项」.

设计要点:
- 唯一真相是 workflow 图本身 (loader 节点的 class_type + field). 不读 health_requirements.json,
  避免两份清单漂移 (LTX distill 曾出现过 graph 跟 health_requirements 不一致).
- /object_info 按 base_url 缓存 (TTL 60s), 运行页每个 preset 打开时懒拉一次, health_check 也共用.
- folder 字段只用于诊断 ("缺这个模型去 ComfyUI/models/<folder>/ 放"), 不参与选项过滤 ——
  ComfyUI 的 /object_info 已经按 loader 节点把对应目录的文件列好了.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import requests

from app import config

_log = logging.getLogger("app.services.model_slots")

# class_type -> (model 字段名, ComfyUI 模型目录, 默认中文 label)
# label 是 UI 默认值, 作者/用户可在 definition 或向导里改.
LOADER_MAP: dict[str, tuple[str, str, str]] = {
    "CheckpointLoaderSimple":   ("ckpt_name",  "checkpoints",      "大模型"),
    "UNETLoader":               ("unet_name",  "diffusion_models", "扩散模型"),
    "UnetLoaderGGUF":           ("unet_name",  "diffusion_models", "扩散模型"),
    "VAELoader":                ("vae_name",   "vae",              "VAE"),
    "CLIPLoader":               ("clip_name",  "text_encoders",    "文本编码器"),
    "CLIPVisionLoader":         ("clip_name",  "clip_vision",      "视觉编码器"),
    "LoraLoader":               ("lora_name",  "loras",            "LoRA"),
    "LoraLoaderModelOnly":      ("lora_name",  "loras",            "LoRA"),
    "LatentUpscaleModelLoader": ("model_name", "upscale_models",   "放大模型"),
}


@dataclass
class ModelSlot:
    """graph 扫描出来的一个 loader 槽位 (不含本机已装列表)."""
    key: str                       # "node_id::field"
    node_id: str
    class_type: str
    field: str
    folder: str
    label: str
    required_filename: str | None  # 工作流自带的模型名 (图里的当前值)


def discover_slots(graph: dict) -> list[ModelSlot]:
    """扫描 ComfyUI API 格式 workflow 图, 返回所有 loader 节点对应的 ModelSlot.

    给「自动查找」/ 健康检查诊断用 —— 列出图里全部 loader, 不论作者是否把它暴露成输入.
    运行页 UI 用 slots_for_preset (以 definition 里 type=model 的条目为准).
    """
    slots: list[ModelSlot] = []
    if not isinstance(graph, dict):
        return slots
    for nid, node in graph.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type")
        mapping = LOADER_MAP.get(ct) if isinstance(ct, str) else None
        if mapping is None:
            continue
        field, folder, label = mapping
        val = (node.get("inputs") or {}).get(field)
        slots.append(ModelSlot(
            key=f"{nid}::{field}",
            node_id=str(nid),
            class_type=ct,
            field=field,
            folder=folder,
            label=label,
            required_filename=val if isinstance(val, str) else None,
        ))
    return slots


def extract_options(object_info: dict, class_type: str, field: str) -> list[str]:
    """从 /object_info 提取某 loader 节点本机已装的模型文件名列表 (纯函数).

    ComfyUI 形状: object_info[class_type].input.required[field] == [ [filename, ...], {widget opts} ]
    按 field 参数化 (不再硬编码 5-tuple). health_check._get_available_models 共用本函数.

    找不到该 class_type / 该 field / 形状不对 → 返回空列表 (不抛).
    """
    node = object_info.get(class_type) if isinstance(object_info, dict) else None
    if not isinstance(node, dict):
        return []
    required = node.get("input", {}).get("required", {})
    val = required.get(field) if isinstance(required, dict) else None
    if isinstance(val, list) and val and isinstance(val[0], list):
        return [str(x) for x in val[0]]
    return []


# --- /object_info 缓存 (按 base_url, TTL 秒) ---
# 运行页每个 preset 打开时拉一次, 60s 内复用; health_check 也走这里, 避免重复全量拉取.
_object_info_cache: dict[str, tuple[float, dict]] = {}
_OBJECT_INFO_TTL: float = 60.0


def fetch_object_info(base_url: str, timeout: int = 8, force: bool = False) -> dict | None:
    """拉取并缓存 ComfyUI /object_info. 失败 / 非 200 / 非对象 → 返回 None (不抛)."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return None
    now = time.time()
    cached = _object_info_cache.get(base)
    if cached and not force and (now - cached[0]) < _OBJECT_INFO_TTL:
        return cached[1]
    try:
        resp = requests.get(f"{base}/object_info", timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception as e:  # 网络层任何异常都不致命 —— 运行页降级成「只显示需求清单」
        _log.debug("[model_slots] /object_info fetch failed for %s: %s", base, e)
        return None
    if not isinstance(data, dict):
        return None
    _object_info_cache[base] = (now, data)
    return data


@dataclass
class SlotView:
    """给前端 API 的槽位视图 (含本机已装列表 + 是否就位)."""
    key: str
    node_id: str
    class_type: str
    field: str
    required_filename: str | None
    available: list[str]
    installed: bool

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "node_id": self.node_id,
            "class_type": self.class_type,
            "field": self.field,
            "required_filename": self.required_filename,
            "available": self.available,
            "installed": self.installed,
        }


def _load_graph(preset_name: str) -> dict | None:
    try:
        path = config.workflow_path(preset_name)
    except Exception:
        return None
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def slots_for_preset(preset_name: str) -> tuple[list[SlotView], bool]:
    """读 definition 的 type=model 条目, 返回 (slots, fetched).

    fetched=False 表示 /object_info 没拉到 (ComfyUI 离线) —— 此时 available=[] 但 slots
    仍返回, 前端能显示「需要 X」清单, 只是不能换.

    以 definition 里作者/向导选了哪些 loader 暴露为准 (type=model 的条目), 不是图里全部
    loader —— 作者可以只暴露主模型、把 VAE 之类锁死.
    """
    from app import scail2_client  # 运行时 base url (跟顶部状态灯/health 同源)
    cfg = config.preset_config(preset_name)
    graph = _load_graph(preset_name)

    # node_id -> class_type (从图里查, 用来取该 loader 的本机已装列表)
    node_classes: dict[str, str] = {}
    if isinstance(graph, dict):
        for nid, node in graph.items():
            if isinstance(node, dict) and isinstance(node.get("class_type"), str):
                node_classes[str(nid)] = node["class_type"]

    base_url = scail2_client.get_base_url() or config.COMFY_BASE_URL
    object_info = fetch_object_info(base_url)
    fetched = object_info is not None

    slots: list[SlotView] = []
    for spec in cfg.get("user_facing_inputs", []):
        if spec.get("type") != "model":
            continue
        nid = str(spec.get("node_id"))
        field = spec.get("field")
        if not field:
            continue
        ct = node_classes.get(nid, "")
        required = spec.get("default")
        if not isinstance(required, str) or not required:
            # 兜底: definition 没写 default 时, 从图里取当前值
            required = _graph_model_value(graph, nid, field)
        available = extract_options(object_info or {}, ct, field) if object_info else []
        slots.append(SlotView(
            key=f"{nid}::{field}",
            node_id=nid,
            class_type=ct,
            field=field,
            required_filename=required,
            available=available,
            installed=bool(required and available and required in available),
        ))
    return slots, fetched


def _graph_model_value(graph: dict | None, node_id: str, field: str) -> str | None:
    if not isinstance(graph, dict):
        return None
    node = graph.get(node_id)
    if not isinstance(node, dict):
        return None
    val = (node.get("inputs") or {}).get(field)
    return val if isinstance(val, str) else None
