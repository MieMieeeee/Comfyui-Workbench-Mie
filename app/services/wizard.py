"""工作流向导 — 解析 ComfyUI workflow JSON + 推断输入类型 + 列出输出.

引导用户把一个 ComfyUI workflow 变成 WebUI 可用的 preset, 不用手工编辑
definition.json. 三个核心函数:

  parse_workflow_api_json(raw)  解析 API 格式 workflow, 返回候选输入字段
  infer_spec(node_id, field, node_def)  按 class_type+field 推断 spec.type
  extract_all_outputs(history, workflow)  遍历 history 所有输出 node

设计依据见 docs/plans (workflow-decouple-wizard). 推断规则基于全量 preset
数据归纳 (见 Explore agent 调研结果), 是软规则 — 用户可在向导 UI 覆盖.
"""
from __future__ import annotations

import json
from typing import Any


# ============================================================
# type 推断 — class_type + field 名 + value 类型 → spec.type
# ============================================================

# 这些 class_type 的 width/height 字段 → image_sizes (多尺寸多选)
_SIZES_LATENT_CLASSES = frozenset({
    "EmptySD3LatentImage",
    "EmptyFlux2LatentImage",
})

# image_sizes 类节点: 一个 spec 同时管 width+height (不拆成两个 int)
# 记录 (node_id) 以便 parse 阶段把同 node 的 width/height 合并成一个 image_sizes spec


def _is_connection_ref(value: Any) -> bool:
    """ComfyUI API 格式里, node 间连接引用是 [node_id_str, slot_index_int].

    用户可输入字段是标量 (str/int/float/bool). 连接引用不是用户输入, 要过滤掉.
    """
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)


def infer_spec(node_id: str, field: str, value: Any, class_type: str = "") -> dict | None:
    """根据 (class_type, field, value) 推断该字段应渲染成什么 spec.type.

    返回 spec dict (含 node_id/field/type/label/default), 或 None 表示
    "这个字段不该暴露给用户" (无法推断成任何输入类型).

    推断规则 (优先级从高到低, 见方案文档):
      1. 连接引用 ([node_id, slot]) → None (不是用户输入)
      2. LoadImage + image → file:image
      3. VHS_LoadVideo + video → file:video
      4. field == seed → int_random
      5. _SIZES_LATENT_CLASSES + width/height → image_sizes (合并)
      6. value 是 bool → bool
      7. value 是 int/float → int
      8. value 是 str → text
    """
    if _is_connection_ref(value):
        return None

    # 规则 2-3: 文件上传槽 (高置信度 — LoadImage/VHS_LoadVideo 明确是用户上传的素材)
    if class_type == "LoadImage" and field == "image":
        return _base_spec(node_id, field, "file:image", default=value, confidence="high")
    if class_type == "VHS_LoadVideo" and field == "video":
        return _base_spec(node_id, field, "file:video", default=value, confidence="high")

    # 规则 4: seed → int_random (高置信度 — seed 几乎总是要暴露给用户)
    if field == "seed":
        return _base_spec(node_id, field, "int_random", default=value or 0, random_default=True, confidence="high")

    # 规则 5: image_sizes (width/height 合并) — 高置信度 (尺寸是核心输出参数)
    if class_type in _SIZES_LATENT_CLASSES and field in ("width", "height"):
        return _base_spec(node_id, field, "image_sizes", default=value, _merge_key=node_id, confidence="high")

    # 规则 6: bool (低置信度 — 可能是开关, 语义不明)
    if isinstance(value, bool):
        return _base_spec(node_id, field, "bool", default=value)

    # 规则 7: 数字 (低置信度 — value/frame_load_cap/cfg 等, 大概率不需要用户改)
    if isinstance(value, (int, float)):
        return _base_spec(node_id, field, "int", default=value)

    # 规则 8: 字符串 (中置信度 — CLIPTextEncode.text 可能是正/负向提示词)
    if isinstance(value, str):
        # CLIPTextEncode 的 text 字段 + 较长内容 → 大概率是提示词, 标 medium
        if class_type == "CLIPTextEncode" and field == "text" and len(value) > 20:
            return _base_spec(node_id, field, "prompt_pool", default=value, confidence="medium")
        # 其它字符串: 短的 (单个词/枚举值) 保持 low
        return _base_spec(node_id, field, "text", default=value)

    return None


def _base_spec(node_id: str, field: str, typ: str, default=None, confidence: str = "low", **extra) -> dict:
    spec = {
        "node_id": str(node_id),
        "field": field,
        "type": typ,
        "label": _default_label(field, typ),
        "default": default,
        # confidence: high = 高置信度推断 (LoadImage/视频/seed/尺寸/提示词), 默认勾选;
        #             low  = 类型兜底 (裸 int/text/bool), 语义不明, 默认不勾选等用户决定.
        "confidence": confidence,
    }
    spec.update(extra)
    return spec


def _default_label(field: str, typ: str) -> str:
    """给字段一个人类可读的默认 label (用户可在向导 UI 改)."""
    labels = {
        "text": "提示词",
        "seed": "种子值",
        "image": "参考图",
        "video": "驱动视频",
        "width": "宽度",
        "height": "高度",
        "frame_load_cap": "帧数限制",
        "steps": "步数",
        "cfg": "CFG",
        "denoise": "重绘幅度",
    }
    if typ == "file:image":
        return "参考图"
    if typ == "file:video":
        return "驱动视频"
    if typ == "image_sizes":
        return "输出尺寸"
    return labels.get(field, field)


# ============================================================
# parse_workflow_api_json — 解析 workflow, 列出候选输入字段
# ============================================================

def parse_workflow_api_json(raw: str) -> dict:
    """解析 ComfyUI API 格式 workflow JSON, 返回候选输入字段 + workflow 本体.

    返回:
      {
        "workflow": <parsed dict>,       # 原样, 供后续 patch/run 用
        "fields": [spec, ...],           # 候选输入字段 (已推断 type)
        "node_count": int,               # workflow 总 node 数 (供 UI 显示)
      }

    过滤逻辑: 只保留标量字段 (排除 node 间连接引用). 同一个 _SIZES_LATENT_CLASSES
    节点的 width+height 合并成一个 image_sizes spec.
    """
    workflow = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(workflow, dict):
        raise ValueError("workflow JSON 顶层必须是 dict[node_id → node_def]")

    fields: list[dict] = []
    # 收集 image_sizes 候选: {node_id: {"width": v, "height": v}}
    sizes_pending: dict[str, dict] = {}

    for node_id, node_def in workflow.items():
        if not isinstance(node_def, dict) or "inputs" not in node_def:
            continue
        class_type = node_def.get("class_type", "")
        inputs = node_def.get("inputs", {})
        for field, value in inputs.items():
            spec = infer_spec(node_id, field, value, class_type)
            if spec is None:
                continue
            # image_sizes: 暂存, 等 width+height 都收集到再合并
            if spec.get("_merge_key"):
                sizes_pending.setdefault(str(node_id), {})[field] = value
                continue
            fields.append(spec)

    # 把 image_sizes 候选合并成单个 spec (一个 node 一个 image_sizes, 不拆 width/height)
    # 合并后仍是 high (尺寸是核心输出参数)
    for nid, dims in sizes_pending.items():
        if "width" in dims and "height" in dims:
            fields.append(_base_spec(nid, "sizes", "image_sizes",
                                     default=[f"{dims['width']}x{dims['height']}"], confidence="high"))
        elif "width" in dims:
            fields.append(_base_spec(nid, "width", "int", default=dims["width"]))
        elif "height" in dims:
            fields.append(_base_spec(nid, "height", "int", default=dims["height"]))

    return {
        "workflow": workflow,
        "fields": fields,
        "node_count": sum(1 for v in workflow.values() if isinstance(v, dict) and "class_type" in v),
    }


# ============================================================
# extract_all_outputs — 遍历 history 所有输出 node 的产物
# ============================================================

# history.outputs[node_id] 里, 产物按这些 key 分类
_OUTPUT_KEYS = ("images", "videos", "gifs", "audio", "files")


def extract_all_outputs(history: dict, workflow: dict | None = None) -> list[dict]:
    """遍历 history.outputs 里每个 node 的每种产物, 返回扁平列表.

    每项: {node_id, title, media_key, filename, subfolder, type, url}
      - node_id: ComfyUI node id (history 不带 title, 用 workflow 的 _meta.title 翻译)
      - title: node 的 _meta.title (找不到用 class_type 或 node_id)
      - media_key: "images"/"videos"/"gifs"/"audio"/"files"
      - type: "output"(最终产物) / "temp"(中间产物)

    不过滤 output/temp — 全返回, 让向导 UI 层决定怎么标注/默认选中.
    (依据: 有些 workflow 的真成品意外落 temp; MaskPreview 调试图也是 temp
    但用户可能想看. 见 scail2_client.extract_primary_video_output 的踩坑注释.)
    """
    if not history:
        return []
    outputs = history.get("outputs", {})
    if not outputs:
        return []

    # 建 node_id → title 映射 (history 不带 title, 从 workflow 补)
    title_map: dict[str, str] = {}
    if workflow and isinstance(workflow, dict):
        for nid, ndef in workflow.items():
            if isinstance(ndef, dict):
                t = ndef.get("_meta", {}).get("title") or ndef.get("class_type")
                if t:
                    title_map[str(nid)] = t

    from app import scail2_client
    results: list[dict] = []
    for node_id in sorted(outputs.keys(), key=lambda x: (len(x), x)):
        node_out = outputs[node_id]
        if not isinstance(node_out, dict):
            continue
        for media_key in _OUTPUT_KEYS:
            items = node_out.get(media_key, [])
            if not (items and isinstance(items, list)):
                continue
            for item in items:
                if not (isinstance(item, dict) and "filename" in item):
                    continue
                filename = item["filename"]
                subfolder = item.get("subfolder", "")
                kind = item.get("type", "output")
                url = scail2_client.get_output_url(filename, subfolder, kind)
                results.append({
                    "node_id": str(node_id),
                    "title": title_map.get(str(node_id), str(node_id)),
                    "media_key": media_key,
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": kind,
                    "url": url,
                })
    return results


# ============================================================
# build_replacements — 向导 spec+values → ComfyUI replacements
# ============================================================

def build_replacements(fields: list[dict], values: dict) -> dict:
    """把向导确认的输入 (fields + values) 转成 ComfyUI patch 的 replacements.

    复用 runner 的映射规则, 但更简单 (向导场景没有 fixed_patches/mirror_to):
      - file:image/file:video → 上传后的文件名 (或 example 默认值)
      - text/prompt_pool/select → 文本
      - int/int_random → 整数
      - image_sizes → width/height/batch_size (拆回两个 field)
      - bool → 布尔

    values 是 {field_index 或 node_id+field: value} 的扁平 dict.
    返回 {node_id: {field: value}}.
    """
    from app.services import form_schema
    replacements: dict[str, dict] = {}
    for spec in fields:
        nid = str(spec["node_id"])
        field = spec["field"]
        typ = spec.get("type", "text")
        default = spec.get("default")
        # values 用 spec 的 field 做键 (向导前端保证唯一); 找不到用 default
        val = values.get(field, default)

        if typ in ("file:image", "file:video"):
            if val:
                replacements.setdefault(nid, {})[field] = val
        elif typ in ("text", "prompt_pool", "select"):
            text = (str(val) if val is not None else "").strip() or (str(default) if default else "")
            replacements.setdefault(nid, {})[field] = text
        elif typ in ("int", "int_random"):
            try:
                num = int(val) if val is not None else int(default or 0)
            except (TypeError, ValueError):
                num = int(default or 0)
            replacements.setdefault(nid, {})[field] = num
        elif typ == "image_sizes":
            # image_sizes 是 ["WxH", ...], 向导只用第一个尺寸跑一次
            sizes = form_schema.parse_sizes(val if val is not None else default)
            if sizes:
                w, h = sizes[0]
                replacements.setdefault(nid, {}).update({"width": w, "height": h, "batch_size": 1})
        elif typ == "bool":
            replacements.setdefault(nid, {})[field] = bool(val)
    return replacements


def run_workflow_once(workflow: dict, replacements: dict, timeout: int = 600) -> dict:
    """用临时 patch 跑一次 workflow, 返回 history (含所有输出 node 产物).

    向导步骤 B 用: 不存 preset definition, 直接 patch + queue + wait + get_history.
    返回 ComfyUI /history/{prompt_id} 的响应 (含 outputs).
    需要 ComfyUI 在跑 (调 scail2_client).
    """
    from app import scail2_client
    patched = scail2_client.patch_workflow(workflow, replacements)
    prompt_id, client_id = scail2_client.queue_prompt(patched)
    # 等 ComfyUI 跑完, drain 状态消息 (向导不需要进度流, 丢掉)
    for _msg in scail2_client.wait_for_completion(prompt_id, timeout=timeout):
        pass
    return scail2_client.get_history(prompt_id)
