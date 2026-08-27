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
import shutil
from pathlib import Path
from typing import Any


# ============================================================
# type 推断 — class_type + field 名 + value 类型 → spec.type
# ============================================================

# 这些 class_type 的 width/height 字段 → image_sizes (多尺寸多选)
_SIZES_LATENT_CLASSES = frozenset({
    "EmptySD3LatentImage",
    "EmptyFlux2LatentImage",
    "EmptyLatentImage",
    "EmptyLatentImageCustomPresets",
})

# image_sizes 类节点: 一个 spec 同时管 width+height (不拆成两个 int)
# 记录 (node_id) 以便 parse 阶段把同 node 的 width/height 合并成一个 image_sizes spec


def _is_connection_ref(value: Any) -> bool:
    """ComfyUI API 格式里, node 间连接引用是 [node_id_str, slot_index_int].

    用户可输入字段是标量 (str/int/float/bool). 连接引用不是用户输入, 要过滤掉.
    """
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)


# loader 节点 → 模型参数类. 复用 services.model_slots 的权威映射 (单一真相),
# 向导解析时把 loader 的模型字段自动标成 type=model/tier=model, 用户只需确认.
# 懒导入避免 wizard 顶层连带 requests/config 加载 (虽然 model_slots 无副作用, 保持克制).
def _loader_model_field(class_type: str) -> tuple[str, str] | None:
    """class_type 是 loader → 返回 (model 字段名, 默认中文 label); 否则 None."""
    if not isinstance(class_type, str):
        return None
    from .model_slots import LOADER_MAP
    mapping = LOADER_MAP.get(class_type)
    if mapping is None:
        return None
    field, _folder, label = mapping
    return field, label


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

    # 规则 3.5: loader 节点的模型字段 → 模型参数类 (高置信度 — loader 的模型文件名就是
    # 该暴露给用户做二次选择的; 选项运行页从本机 /object_info 动态拉). 只匹配 loader 的
    # 模型字段本身, 同节点其它字段 (如 weight_dtype) 走后面的通用规则.
    loader = _loader_model_field(class_type)
    if loader and field == loader[0]:
        return _base_spec(node_id, field, "model", default=value, confidence="high",
                          tier="model", label=loader[1])

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
    spec.update(_default_spec_options(typ))
    spec.update(extra)
    return spec


def _default_spec_options(typ: str) -> dict:
    """向导生成配置的通用显示元数据。"""
    if typ == "image_sizes":
        # presets / allow_custom 走全局 (统一显示与 zimage/sca12 一致),
        # form_schema.enrich_preset_config 会在 preset_config 出口处注入.
        # 这里只留 help 文案 (向导建的工作流可以独立调一句).
        return {
            "help": "勾选多个预设尺寸, 或填自定义宽×高 (每个尺寸出一张图)。",
        }
    if typ == "int_random":
        return {
            "min": 0,
            "max": 9223372036854776000,
            "step": 1,
            "help": "勾选随机会在每次运行时生成新种子；取消后使用固定数值。",
        }
    if typ in ("text", "prompt_pool"):
        return {"max_chars": 2000, "help": "描述希望生成的内容、风格与构图。"}
    if typ == "file:image":
        return {"help": "上传本次生成使用的参考图片。"}
    if typ == "file:video":
        return {"help": "上传本次生成使用的驱动视频。"}
    if typ == "model":
        return {"help": "本工作流需要的模型；运行页可下拉换成本机已装的同类型模型。"}
    return {}


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


# 向导运行期专用字段 — 落盘 definition 时要剥离 (它们只服务于向导 UI / 推断过程,
# runner/form_schema/validator 从不读). 用 frozenset 让 strip_runtime_fields 不会被
# 误传 list. _merge_key 带 _ 前缀也属于这一类 (parse 阶段临时用).
_RUNTIME_SPEC_FIELDS = frozenset({
    "class_type", "confidence", "current_value", "node_title", "enabled", "_merge_key",
})


def strip_runtime_fields(spec: dict) -> dict:
    """剥离向导运行期字段, 返回干净的 spec dict (不污染入参).

    wizard 生成的 spec 带 class_type/confidence/current_value/node_title/enabled 等
    向导 UI 专用字段. 这些对 runner/form_schema/validator 无用, 留在 definition 里
    只增加体积 + 让 spec 语义看着复杂. 落盘前 (wizard_save) 调本函数过滤.

    保留: node_id/field/type/label/default/help/tier/max_chars/example_key/
          manifest_role/min/max/step/random_default/min_width/min_height/... 等运行字段.
    """
    if not isinstance(spec, dict):
        return spec
    return {k: v for k, v in spec.items() if k not in _RUNTIME_SPEC_FIELDS}


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
        node_title = node_def.get("_meta", {}).get("title", "") or class_type
        inputs = node_def.get("inputs", {})
        for field, value in inputs.items():
            spec = infer_spec(node_id, field, value, class_type)
            if spec is None:
                continue
            # 注入节点上下文 (供向导 UI 显示, 帮用户判断字段语义)
            spec["node_title"] = node_title
            spec["class_type"] = class_type
            spec["current_value"] = value
            # image_sizes: 暂存, 等 width+height 都收集到再合并
            if spec.get("_merge_key"):
                sizes_pending.setdefault(str(node_id), {})[field] = value
                continue
            fields.append(spec)

    # 把 image_sizes 候选合并成单个 spec (一个 node 一个 image_sizes, 不拆 width/height)
    # 合并后仍是 high (尺寸是核心输出参数)
    for nid, dims in sizes_pending.items():
        node_title = ""
        class_type = ""
        ndef = workflow.get(nid) or workflow.get(int(nid))
        if isinstance(ndef, dict):
            class_type = ndef.get("class_type", "")
            node_title = ndef.get("_meta", {}).get("title", "") or class_type
        if "width" in dims and "height" in dims:
            fields.append(_base_spec(nid, "sizes", "image_sizes",
                                     default=[f"{dims['width']}x{dims['height']}"], confidence="high"))
        elif "width" in dims:
            fields.append(_base_spec(nid, "width", "int", default=dims["width"]))
        elif "height" in dims:
            fields.append(_base_spec(nid, "height", "int", default=dims["height"]))
        # 给合并后的 image_sizes 也注入节点上下文
        if fields:
            fields[-1]["node_title"] = node_title
            fields[-1]["class_type"] = class_type
            fields[-1]["current_value"] = dims

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
        elif typ == "float":
            try:
                num = float(val) if val is not None else float(default if default is not None else 0.0)
            except (TypeError, ValueError):
                num = float(default if default is not None else 0.0)
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


def prepare_example(
    preset_name: str,
    fields: list[dict],
    values: dict,
    selected_output: dict,
) -> dict:
    """保存试跑参数，并把选中的 ComfyUI 产物复制为静态示例。"""
    from app import config

    if not selected_output:
        raise ValueError("必须选择一个最终输出")
    filename = Path(str(selected_output.get("filename", ""))).name
    if not filename:
        raise ValueError("最终输出缺少文件名")

    kind = selected_output.get("type", "output")
    if kind == "temp":
        source_root = config.COMFY_INSTALL_DIR / "temp"
    else:
        source_root = config.COMFY_OUTPUT_DIR
    source_root = source_root.resolve()
    source = (source_root / str(selected_output.get("subfolder", "")) / filename).resolve()
    try:
        source.relative_to(source_root)
    except ValueError as exc:
        raise ValueError("输出路径不在 ComfyUI 产物目录内") from exc
    if not source.is_file():
        raise FileNotFoundError(f"找不到本次运行产物: {source}")

    ext = source.suffix.lower()
    media_key = selected_output.get("media_key", "")
    preview_key = (
        "preview_image" if media_key == "images" else
        "preview_audio" if media_key == "audio" else
        "preview_video"
    )
    dest_dir = config.REPO_ROOT / "app" / "static" / "examples"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{preset_name}{ext}"
    shutil.copy2(source, dest)

    example = {}
    for spec in fields:
        key = spec.get("example_key") or spec.get("field")
        if key:
            example[key] = values.get(spec.get("field"), spec.get("default"))
    example[preview_key] = f"app/static/examples/{dest.name}"
    return example


def run_workflow_once(workflow: dict, replacements: dict, timeout_sec: int = 600) -> dict:
    """用临时 patch 跑一次 workflow, 返回 history (含所有输出 node 产物).

    向导步骤 ④ 用: 不存 preset definition, 直接 patch + queue + wait + get_history.
    返回 ComfyUI /history/{prompt_id} 的响应 (含 outputs).
    需要 ComfyUI 在跑 (调 scail2_client).
    """
    from app import scail2_client
    # validate_after=False: 向导跑的是用户临时上传的 workflow, 没有 preset_config,
    # 无法也不需要跑 schema 校验 (那是给作者手写 definition 用的 config-drift 检查).
    patched = scail2_client.patch_workflow(workflow, replacements, validate_after=False)
    prompt_id, _client_id = scail2_client.queue_prompt(patched)
    # 等 ComfyUI 跑完, drain 状态消息 (向导不需要进度流, 丢掉)
    for _msg in scail2_client.wait_for_completion(prompt_id, timeout_sec=timeout_sec):
        pass
    return scail2_client.get_history(prompt_id)
