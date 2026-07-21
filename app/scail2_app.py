"""SCAIL-2 Web UI — Gradio 入口。

上传后自动 preview。表单从 params.json 动态生成。
"""



from __future__ import annotations

# bootstrap: 让 `py app/scail2_app.py` 能跑
import sys as _sys
import os as _os
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

# --- 离线自包含开关(必须在 import gradio 之前设置)---
# 本 WebUI 配套 ComfyUI 整合包发布,必须在无外网环境下也能正常打开。
# 这些环境变量切断 Gradio / huggingface_hub 的所有外网探测(telemetry /
# 版本检查 / 模型仓库 ping),避免离线时 SPA 卡在加载界面。
_os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
_os.environ.setdefault("HF_HUB_OFFLINE", "1")
_os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import json
import logging
import math
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import gradio as gr

from app import config
from app import scail2_client
from app import history
from app.workflow_validator import WorkflowValidationError
from app.scail2_client import (
    ComfyUIError,
    ConnectionError_,
    ProtocolError_,
)

# log 写文件（独立进程看不到 stdout）
_LOG_PATH = _REPO_ROOT / "app" / "data" / "gradio_run.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=str(_LOG_PATH), level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger("scail2_app")

# 跨 tab 状态：历史记录点 "🔄 加载到运行" 需要跳到“运行” tab + 切 preset + 填表单，
_ALL_INPUTS_FLAT: list = []
_WF_RADIO_REF = None  # type: ignore[assignment]
_TABS_REF = None  # type: ignore[assignment]
# _AUTO_LOADED: 切换过/手动加载过的 preset, 下次再切回去时不再 auto-load example.
# 设计:
#   - 首次切到 preset (不在集合) -> auto-load example + add to set
#   - 已加载过 (在集合)          -> 返回 gr.update() 保留用户当前输入
# 这样切到别的 workflow 再回来, 上传的文件 / 输入的提示词 不会被 example 覆盖.
# 加载到 (1) 示例按钮 (2) 上次成功参数 (3) 历史 tab “加载到运行” 都把对应 preset 加入此集合,
# 保持“用户最后一次显式操作”的状态.
_AUTO_LOADED: set = set()

# 历史 tab 行点击查找缓存: key=(preset_filter_raw, status_filter_raw), value=runs 列表。
# review 2026-07-17 历史卡死修复: 之前历史 Dataframe 没有 df.select 处理器, 点行无反应,
# 从 cache 查 run, 渲染对应详情卡片。cache 只用于 select 查找; refresh 按钮永远重新
# 读盘覆盖 cache, 不会跟磁盘长期不同步。


def _iter_preset_names():
    """顺序返回所有 preset name（与 build_ui 里 preset_inputs_map 的顺序一致）。
    build_ui 里是走 config.list_workflows()（按 order 排序），这里复用同一个函数。"""
    return [w["name"] for w in config.list_workflows()]

def _resolve_auto_load_updates(preset_inputs_map, name):
    """切换 workflow radio 时, 给每个 preset 的 input 决定用 example 值还是 gr.update()。

    独立提取成模块级函数 (review 2026-07-11 P-state-preserve) 是为了可测:
    在 build_ui 里它是 closure, 单元测试拿不到。提取后用 preset_inputs_map 作
    参数即可直接调, 测试用例可构造一个最小的 preset_inputs_map 验证契约。

    核心契约:
      name not in _AUTO_LOADED -> 首次切到, auto-load example, add to set
      name in _AUTO_LOADED    -> 已加载过, 用 gr.update() 保留用户当前输入, 不重置回 example
      其它 preset                -> gr.update() 保持原状

    History tab "load to run" / "load example" button / "load last run" button
    都会把对应 preset 加入 _AUTO_LOADED, 保证后续切回去不覆盖。

    返回 list, 长度 == sum(len(ins) for ins in preset_inputs_map.values()),
    顺序与 preset_inputs_map 一致 (按 preset 顺序, 每个 preset 内按 user_facing_inputs 顺序)。
    返回值要么是 example 算出来的真实值, 要么是 gr.update() (no-op)。
    """
    result = []
    for preset_name, _ins in preset_inputs_map.items():
        if preset_name == name:
            if preset_name in _AUTO_LOADED:
                # already loaded, user edits / uploads / inputs must be preserved
                result.extend([gr.update() for _in in _ins])
            else:
                # first switch -> auto-load example
                _AUTO_LOADED.add(preset_name)
                try:
                    result.extend(example_to_form_values(preset_name))
                except Exception:
                    result.extend([inp.value for inp in _ins])
        else:
            # non-active preset: use gr.update() to keep current state
            result.extend([gr.update() for _in in _ins])
    return result



# [迁移 2026-07-21] get_video_frames / estimated_segments / _file_extension /
# _file_size_mb / validate_inputs 已抽到 app.services.form_schema.
from app.services.form_schema import (
    get_video_frames,
    estimated_segments,
    _file_extension,
    _file_size_mb,
    validate_inputs,
)


# --- 表单 schema → Gradio components ---

# [迁移 2026-07-21] parse_sizes + _SIZE_PAT 已抽到 app.services.form_schema.
from app.services.form_schema import parse_sizes, _SIZE_PAT


def _build_input_component(spec):
    label = spec["label"]
    typ = spec["type"]
    if typ == "file:image":
        return gr.File(
            label=label,
            file_types=[str(e) for e in config.ALLOWED_IMAGE_EXT],
            type="filepath",
        )
    if typ == "file:video":
        return gr.File(
            label=label,
            file_types=[str(e) for e in config.ALLOWED_VIDEO_EXT],
            type="filepath",
        )
    if typ in ("text", "prompt_pool"):
        # prompt_pool 主组件同 text；随机按钮在 _render_workflow_form 里按 type 额外加
        return gr.Textbox(
            label=label, value=spec.get("default", ""), max_lines=6,
            placeholder=spec.get("help") or f"≤{spec.get('max_chars', 2000)} 字符。留空用默认值。",
            info=spec.get("help"),
        )
    if typ == "image_sizes":
        # presets 支持「用途标签化」(第四阶段 §B): 每条可以是
        #   "1024x1024"                          纯字符串(向后兼容)
        #   {"label": "🎬 1280×720 ｜ 16:9", "value": "1280x720"}   带用途文案
        # 归一成 Gradio 的 (label, value) 元组。parse_sizes 只吃 value，
        # label 不进解析路径 —— 保持严格 fullmatch 契约不变。
        raw = spec.get("presets", ["1024x1024", "1280x720", "720x1280"])
        choices = []
        for p in raw:
            if isinstance(p, dict) and "value" in p:
                choices.append((p.get("label", p["value"]), p["value"]))
            else:
                choices.append((p, p))
        return gr.CheckboxGroup(
            choices=choices,
            value=spec.get("default", ["1024x1024"]),
            label=label,
            info=spec.get("help"),
            interactive=True,
            elem_classes=["sizes-cards"],
        )
    if typ == "bool":
        return gr.Checkbox(
            value=bool(spec.get("default", False)),
            label=label,
            info=spec.get("help"),
        )
    if typ == "select":
        # 固定选项下拉 (audio preset 的 language / model_choice 用)
        # choices 可以是 ["Chinese", "English", ...] 字符串列表, 也支持
        # [{"label": "中文", "value": "Chinese"}] (与 image_sizes 的 label/value 模式一致).
        raw_choices = spec.get("choices", [])
        choices = []
        for c in raw_choices:
            if isinstance(c, dict) and "value" in c:
                choices.append((c.get("label", c["value"]), c["value"]))
            else:
                choices.append((c, c))
        return gr.Dropdown(
            choices=choices,
            value=spec.get("default"),
            label=label,
            info=spec.get("help"),
            interactive=True,
        )
    if typ == "int_random":
        # 「随机 checkbox + 数值 input」组合, 比 Slider 更适合 seed:
        #   - seed 在实践中只有两种意图: 每跑随机 / 固定值; checkbox 表达
        #     这个意图比 Slider 直观
        #   - 输入框支持任意 int64 (Slider 在大值下拖不动)
        #   - schema 上 min/max 仍跟 ComfyUI 实际能力对齐 (int64)
        # random_default 决定 checkbox 初始状态: true=默认随机, false=用 default value
        # example_to_form_values / _manifest_to_form_values 见同文件末尾的 seed 处理
        checkbox = gr.Checkbox(
                label="随机",
                value=bool(spec.get("random_default", True)),
                info="勾上则忽略下方数值,每张图独立随机",
            )
        number = gr.Number(
                label=label,
                value=spec.get("default", 0),
                minimum=spec.get("min", 0),
                maximum=spec.get("max", (1 << 63) - 1),
                step=spec.get("step", 1),
                precision=0,
                info=spec.get("help"),
            )
        return [checkbox, number]
    if typ == "int":
        # 用 gr.Number 不用 gr.Slider: Gradio 6.20.0 的 Slider 在 advanced panel
        # 里视觉 chrome (track/thumb/value display) 渲染挂掉, 留下 status-tracker
        # 永久 loading。int_random 用的就是 Number, 已知能渲染。
        return gr.Number(
            value=spec["default"],
            minimum=spec["min"], maximum=spec["max"],
            step=spec.get("step", 1), precision=0,
            label=label, info=spec.get("help"),
        )
    raise ValueError(f"unknown input type: {typ}")


def _build_form(preset_cfg):
    """扁平化构建表单组件列表。

    大多数 spec 1 个 spec -> 1 个 component; int_random 是 1 个 spec -> 2 个 components
    (Checkbox + Number)。返回的列表按 user_facing_inputs 顺序, 但 int_random
    占 2 个位置 — 调用方需要按 spec 类型决定如何消费 (run_image_workflow 内部
    会合并 int_random 的 2 个值为单个 seed)。
    """
    out = []
    for spec in preset_cfg["user_facing_inputs"]:
        c = _build_input_component(spec)
        if isinstance(c, list):
            out.extend(c)
        else:
            out.append(c)
    return out




# [迁移 2026-07-21] example_to_form_values / _manifest_to_form_values /
# _resolve_example_file / _is_comfy_input_file / _resolve_upload_name 已抽到
# app.services.form_schema.
from app.services.form_schema import (
    example_to_form_values,
    _manifest_to_form_values,
    _resolve_example_file,
    _is_comfy_input_file,
    _resolve_upload_name,
)

def run_workflow(preset_name, *component_values):
    """运行指定 preset 的 workflow。preset_name 决定走哪个模板。

    component_values 顺序对应 preset 的 user_facing_inputs（由 UI 按序传入）。
    生成器 yield (status_msg, output_url) 给 Gradio 流式更新。
    同时用 gr.Progress 推进度条（0~1 + 描述）。
    """
    progress = gr.Progress()
    _log.info(f"[run_workflow] ENTRY preset={preset_name}, {len(component_values)} values")
    try:
        progress(0.02, desc="准备中…")
        yield "[READY] preparing…", None
    except Exception as e:
        _log.error("[run_workflow] early yield exception: " + repr(e), exc_info=True)
        yield "[ERROR] early yield: " + repr(e), None
        raise
    preset_cfg = config.preset_config(preset_name)
    output_kind = _output_kind(preset_cfg)
    _log.debug(f"start preset={preset_name}, {len(component_values)} component values")

    inputs_spec = preset_cfg["user_facing_inputs"]
    text_by_field: dict[tuple[str, str], str] = {}
    file_by_type: dict[str, str] = {}
    int_by_field: dict[tuple[str, str], int] = {}
    component_idx = 0
    for spec in inputs_spec:
        nid = str(spec["node_id"])
        typ = spec["type"]
        field = spec["field"]
        value = component_values[component_idx] if component_idx < len(component_values) else None
        if typ in ("text", "prompt_pool", "select"):
            text_by_field[(nid, field)] = value or ""
        elif typ == "file:image":
            file_by_type["image"] = value
        elif typ == "file:video":
            file_by_type["video"] = value
        elif typ == "int":
            int_by_field[(nid, field)] = int(value) if value is not None else spec.get("default", 1)
        elif typ == "int_random":
            number = component_values[component_idx + 1] if component_idx + 1 < len(component_values) else spec.get("default", 0)
            int_by_field[(nid, field)] = random.randint(1, 10**12) if bool(value) else int(number)
            component_idx += 1
        component_idx += 1
    ref_path = file_by_type.get("image")
    drive_path = file_by_type.get("video")

    started_at = datetime.now(timezone.utc)
    prompt_id_final: str | None = None
    final_output: dict | None = None
    final_status = "failure"
    final_error: str | None = None

    err = validate_inputs(ref_path, drive_path, preset_cfg)
    if err:
        _log.debug(f"validate fail: {err}")
        gr.Error(err)
        yield f"❌ {err}", None
        return
    _log.debug("validate pass")

    # 解析 user_facing_inputs 里 file:image/file:video 的有无, 决定要不要走 upload 步骤
    has_image_input = any(s.get("type") == "file:image" for s in inputs_spec)
    has_video_input = any(s.get("type") == "file:video" for s in inputs_spec)

    if has_image_input:
        progress(0.10, desc="上传参考图…")
        yield "⏳ [1/5] uploading reference image…", None
        try:
            ref_name = _resolve_upload_name(ref_path, kind="image")
        except (ComfyUIError, FileNotFoundError) as e:
            gr.Error(str(e))
            progress(0, desc=f"❌ 上传失败: {e}")
            yield f"❌ upload ref: {e}", None
            return
    if has_video_input:
        progress(0.20, desc="上传驱动视频…")
        yield "⏳ [2/5] uploading drive video…", None
        try:
            drive_name = _resolve_upload_name(drive_path, kind="file")
        except (ComfyUIError, FileNotFoundError) as e:
            gr.Error(str(e))
            progress(0, desc=f"❌ 上传失败: {e}")
            yield f"❌ upload drive: {e}", None
            return

    progress(0.30, desc="组装 workflow…")
    yield "⏳ [3/5] loading + patching workflow…", None
    try:
        wf = scail2_client.load_workflow_template(preset_name)
        replacements: dict[str, dict[str, Any]] = {}
        # 先合并 preset 级别的固定 patch（如 SCAIL2 mode: node 353）
        for nid, fields in (preset_cfg.get("fixed_patches") or {}).items():
            replacements[nid] = dict(fields)
        for spec in inputs_spec:
            nid = str(spec["node_id"])
            field = spec["field"]
            typ = spec["type"]
            if typ == "file:image":
                # merge: 同一 node 上可能还有 int/text 等其它 spec, 不要覆盖
                if nid in replacements:
                    replacements[nid][field] = ref_name
                else:
                    replacements[nid] = {field: ref_name}
            elif typ == "file:video":
                # merge: 同一 node 上可能还有 int/text 等其它 spec, 不要覆盖
                if nid in replacements:
                    replacements[nid][field] = drive_name
                else:
                    replacements[nid] = {field: drive_name}
                # 同一份素材绑多个 node（典型：SCAIL2 的 node 369 Drive Slice + node 469
                # Full Source 取音频 / 元信息）。必须绑同一份视频，否则音频丢失 / 帧数不匹配
                # / MieLoopEnd 越界。spec.also_patch 是 [{node_id, field}, ...] 列表，
                # 同一份 drive_name 写到这些 node 上。
                for _extra in (spec.get("also_patch") or []):
                    _enid = str(_extra["node_id"])
                    _efield = _extra["field"]
                    if _enid in replacements:
                        replacements[_enid][_efield] = drive_name
                    else:
                        replacements[_enid] = {_efield: drive_name}
            elif typ in ("text", "prompt_pool", "select"):
                raw = text_by_field.get((nid, field), "")
                final = (raw or "").strip() or (spec.get("default") or config.DEFAULT_PROMPT_TEXT)
                # merge: 同一 node 上可能还有 int/file 等其它 spec, 不要覆盖
                if nid in replacements:
                    replacements[nid][field] = final
                else:
                    replacements[nid] = {field: final}
                # mirror_to: 把同一个文本值复制到其它节点的 field 上 (典型: SCAIL2 的
                # 348.text (CLIPTextEncode) + 540.text (StringHash, 喂 cache key) 必须同步,
                # 否则 cache key 永远哈希到 workflow 里硬编码的 "human" 而不是用户实际输入。
                # 也兼容 also_patch 这个老名字, 行为一致。
                for _extra in (spec.get("mirror_to") or spec.get("also_patch") or []):
                    _enid = str(_extra["node_id"])
                    _efield = _extra["field"]
                    if _enid in replacements:
                        replacements[_enid][_efield] = final
                    else:
                        replacements[_enid] = {_efield: final}
            elif typ in ("int", "int_random"):
                default = spec.get("default", 1)
                val = int_by_field.get((nid, field), default)
                # max_segments=0 (默认) 不 patch，保留 workflow 原始的 [495, 1] 引用
                if nid == "479" and val == 0:
                    pass
                else:
                    # merge: 同一 node 上可能还有 file:video 等其它 spec, 不要覆盖
                    if nid in replacements:
                        replacements[nid][field] = val
                    else:
                        replacements[nid] = {field: val}
        patched = scail2_client.patch_workflow(
            wf, replacements, preset_config=preset_cfg, validate_after=True,
        )
    except (WorkflowValidationError, FileNotFoundError) as e:
        gr.Error(str(e))
        yield f"❌ patch: {e}", None
        return

    progress(0.40, desc="入队 ComfyUI…")
    yield "⏳ [4/5] queuing prompt to ComfyUI…", None
    try:
        prompt_id, client_id = scail2_client.queue_prompt(patched)
    except (ComfyUIError, ProtocolError_) as e:
        gr.Error(str(e))
        progress(0, desc=f"❌ 入队失败: {e}")
        yield f"❌ queue: {e}", None
        return
    prompt_id_final = prompt_id
    yield f"⏳ [4/5] queued: {prompt_id[:8]}…", None

    video_url = None
    progress(0.45, desc="等待 ComfyUI 执行…")
    yield "⏳ [5/5] waiting for ComfyUI execution…", None
    _wait_p = 0.45
    # P1: build node_id -> title map from patched workflow so status_bar shows
    # "KSampler" / "Load Image" instead of leaking "node 367" (AGENTS.md rule).
    _title_map = scail2_client.build_node_title_map(patched)
    # P0: 后台 ws 线程拿 KSampler/SamplerCustom step value/max, 拼 "12/20" 进状态。
    # 连不上/断开静默降级到 /history 轮询 (start_progress_listener 返回空队列)。
    _pq = scail2_client.start_progress_listener(client_id)
    try:
        for status_msg in scail2_client.wait_for_completion(
            prompt_id, title_map=_title_map, progress_queue=_pq,
        ):
            # P2: 有真实 step 进度时 (wait_for_completion yield 的 "12/20") 用真实百分比,
            # 映射到 [0.45, 0.92] 区间 (留 0.08 给最终完成)。无 step 才回退匀速估算。
            _step = _extract_step_progress(status_msg)
            if _step is not None:
                _ratio = _step[0] / _step[1]
                _wait_p = min(0.92, 0.45 + _ratio * (0.92 - 0.45))
            else:
                # 进度按轮询渐进推进（0.45 → 0.92），留 0.08 给最终完成
                _wait_p = min(0.92, _wait_p + 0.02)
            progress(_wait_p, desc=status_msg.lstrip("⏳✅❌⏰ ").strip()[:40] or "执行中…")
            if status_msg.startswith("✅"):
                try:
                    hist = scail2_client.get_history(prompt_id)
                    if output_kind == "image":
                        image_outputs = scail2_client.extract_all_image_outputs(hist or {})
                        # Prefer type=output (final SaveImage), fallback type=temp (PreviewImage).
                        # Mirrors commit 2113045 for video (extract_primary_video_output).
                        # Defensive: if a workflow emits both (e.g. final SaveImage + intermediate
                        # PreviewImages for SAM mask / blend preview / upscale), this filter picks
                        # the user-facing final image. Add a regression test before relying on
                        # this for any specific workflow (see tests/test_run_workflow_image_prefer_output.py).
                        preferred = [im for im in image_outputs if im.get("type") == "output"]
                        out = preferred[0] if preferred else (image_outputs[0] if image_outputs else None)
                    else:
                        out = scail2_client.extract_primary_video_output(hist or {})
                    if out:
                        view_url = scail2_client.get_output_url(
                            out["filename"], out["subfolder"], out["type"]
                        )
                        final_output = {
                            "filename": out["filename"],
                            "subfolder": out["subfolder"],
                            "type": out["type"],
                        }
                        # output_box 是 gr.HTML，直接用 /view URL（_media_to_html 转 <video> 标签）
                        video_url = view_url
                except Exception as e:
                    status_msg = f"{status_msg} (拉 outputs 失败: {e})"
            kind, err = _extract_status_kind(status_msg)
            if kind is not None:
                final_status = kind
                if err:
                    final_error = err
            yield status_msg, video_url
            if status_msg.startswith(("✅", "❌", "⏰")):
                break
    finally:
        # 通知 ws 后台线程退出 (daemon=True 已保进程退出不卡, 这里及时收尾)
        _pq.put(None)

    # 最终进度：成功 1.0，失败/超时也归零并标注
    if final_status == "success":
        progress(1.0, desc="完成")
    else:
        progress(0, desc=f"❌ {final_status}")

    finished_at = datetime.now(timezone.utc)
    if prompt_id_final:
        try:
            fps = int_by_field.get(("367", "value"), 81)
            pre = int_by_field.get(("464", "value"), 5)
            mx = int_by_field.get(("479", "int_range_end"), 0)
            video_frames = get_video_frames(drive_path) if drive_path else None
            est_seg = estimated_segments(video_frames, fps, pre, max_segments=mx) if video_frames else None
            manifest = history.build_manifest(
                prompt_id=prompt_id_final,
                started_at_iso=started_at.isoformat(),
                finished_at_iso=finished_at.isoformat(),
                duration_sec=int((finished_at - started_at).total_seconds()),
                preset=preset_name,
                reference_image=Path(ref_path).name if ref_path else "",
                drive_video=Path(drive_path).name if drive_path else "",
                prompt_text=replacements.get("360", {}).get("text", "") or replacements.get("6", {}).get("text", ""),
                frames_per_segment=fps,
                pre_drop_frames=pre,
                max_segments=mx,
                video_frames=video_frames,
                estimated_segments=est_seg,
                status=final_status,
                cache_hit=False,
                output=final_output,
                error=final_error,
                # SCAIL2 三个独立 prompt 给历史 → 运行 还原用
                ref_prompt=replacements.get("362", {}).get("text", ""),
                drive_prompt=replacements.get("348", {}).get("text", ""),
                main_prompt=replacements.get("360", {}).get("text", ""),
            )
            history.write_manifest(manifest)
            _log.debug(f"manifest written: {prompt_id_final[:8]}, est_seg={est_seg}")
        except Exception as e:
            _log.error(f"manifest write failed: {e}")


# --- 文生图主流程（多尺寸循环）---

def run_image_workflow(preset_name, *component_values):
    """文生图 workflow（如 zimage）。支持多尺寸：每个尺寸 queue 一次，收集所有图。

    component_values 顺序对应 preset 的 user_facing_inputs：
    zimage 是 [prompt(text), sizes(checkboxgroup), seed(int)]。

    生成器 yield (status_msg, image_url_or_gallery)。
    最新的 image url 喂给 gr.Image（多张时显示最后一张，manifest 记录全部）。
    """
    from app import prompts as prompts_mod
    progress = gr.Progress()
    _log.info(f"[run_image] ENTRY preset={preset_name}, {len(component_values)} values")
    yield "[READY] preparing image gen…", None

    preset_cfg = config.preset_config(preset_name)
    inputs_spec = preset_cfg["user_facing_inputs"]

    # 把 component_values 映射到 spec
    # 大多数 spec 1:1 占用 component_values 1 项; int_random 占 2 项 (Checkbox + Number)。
    # 用 while + i 推进而不是 zip, 这样 int_random 能一次取 2 个值。
    prompt_text = ""
    sizes_raw = None
    seed_val = 0
    prompt_node_id = None
    sizes_node_id = None
    seed_node_id = None
    i = 0
    while i < len(inputs_spec):
        spec = inputs_spec[i]
        typ = spec["type"]
        nid = str(spec["node_id"])
        if typ == "prompt_pool":
            prompt_text = component_values[i] or ""
            prompt_node_id = nid
            i += 1
        elif typ == "image_sizes":
            sizes_raw = component_values[i]
            sizes_node_id = nid
            i += 1
        elif typ == "int_random":
            # component_values[i] = Checkbox state (bool)
            # component_values[i+1] = Number value
            randomize = bool(component_values[i]) if component_values[i] is not None else True
            number_val = component_values[i + 1] if i + 1 < len(component_values) else spec.get("default", 0)
            # checkbox 勾上 -> seed_val=0 (后续 actual_seed 用 random.randint 生成);
            # 不勾       -> seed_val=number (固定值)
            seed_val = 0 if randomize else int(number_val) if number_val is not None else spec.get("default", 0)
            seed_node_id = nid
            i += 2
        elif typ == "int":
            seed_val = int(component_values[i]) if component_values[i] is not None else spec.get("default", 0)
            seed_node_id = nid
            i += 1
        else:
            # 未来加新 type 在这里兜底,避免 i 死循环
            i += 1

    # prompt 为空 → 用默认（不强制随机，随机由 UI 按钮触发）
    prompt_text = (prompt_text or "").strip() or preset_cfg.get("user_facing_inputs", [{}])[0].get("default", "Photorealistic, ultra-detailed.")

    # 解析尺寸
    sizes = parse_sizes(sizes_raw)
    if not sizes:
        sizes = [(1024, 1024)]
    _log.debug(f"[run_image] prompt_len={len(prompt_text)} sizes={sizes} seed={seed_val}")

    started_at = datetime.now(timezone.utc)
    prompt_ids: list[str] = []
    all_outputs: list[dict] = []
    final_status = "success"
    final_error: str | None = None
    gallery_urls: list[str] = []  # 累积已完成的图 URL，喂给 gr.Gallery（Gallery 需 list）

    try:
        wf_base = scail2_client.load_workflow_template(preset_name)
    except (FileNotFoundError, WorkflowValidationError) as e:
        gr.Error(str(e))
        yield f"❌ load: {e}", None
        return
    # P1: node_id -> title map, 在尺寸循环外建一次 (workflow 模板不变, title 通用)
    _title_map = scail2_client.build_node_title_map(wf_base)

    yield f"⏳ 准备生成 {len(sizes)} 张图…", None

    progress(0.05, desc=f"准备生成 {len(sizes)} 张图…")
    yield f"⏳ 准备生成 {len(sizes)} 张图…", None

    for idx, (w, h) in enumerate(sizes, 1):
        # seed=0 → 每尺寸独立随机；>0 → 固定
        actual_seed = seed_val if seed_val and seed_val > 0 else random.randint(1, 10**12)
        replacements = {}
        if prompt_node_id:
            replacements[prompt_node_id] = {"text": prompt_text}
        if seed_node_id:
            replacements[seed_node_id] = {"seed": actual_seed}
        # image_sizes 是复合 type：直接 patch width/height（sizes_node_id 指向 EmptySD3LatentImage）
        if sizes_node_id:
            replacements[sizes_node_id] = {"width": w, "height": h, "batch_size": 1}

        # 该尺寸占的进度区间：[(idx-1)/n, idx/n]
        seg_start = (idx - 1) / len(sizes)
        seg_end = idx / len(sizes)
        progress(seg_start + 0.02, desc=f"[{idx}/{len(sizes)}] {w}x{h} 生成中…")
        yield f"⏳ [{idx}/{len(sizes)}] {w}x{h} seed={actual_seed}…", None
        try:
            patched = scail2_client.patch_workflow(
                wf_base, replacements, preset_config=preset_cfg, validate_after=False,
            )
            prompt_id, client_id = scail2_client.queue_prompt(patched)
            prompt_ids.append(prompt_id)
        except (ComfyUIError, ProtocolError_, WorkflowValidationError, FileNotFoundError) as e:
            gr.Error(str(e))
            final_status = "failure"
            final_error = str(e)
            yield f"❌ [{idx}/{len(sizes)}] queue failed: {e}", list(gallery_urls)
            continue

        # P0: 每个尺寸独立 ws 监听 (各自有自己的 client_id)
        _seg_pq = scail2_client.start_progress_listener(client_id)
        # 轮询这一个尺寸
        _seg_p = seg_start
        try:
            for status_msg in scail2_client.wait_for_completion(
                prompt_id, title_map=_title_map, progress_queue=_seg_pq,
            ):
                kind, err = _extract_status_kind(status_msg)
                if kind == "failure":
                    final_status = "failure"
                    if err:
                        final_error = err
                elif kind == "timeout":
                    final_status = "timeout"
                # P3: 有真实 step 时 (当前尺寸内 KSampler value/max), 把 step 填进
                # 当前尺寸的 [seg_start, seg_end] 区间; 无 step 才回退匀速估算。
                _step = _extract_step_progress(status_msg)
                if _step is not None:
                    _ratio = _step[0] / _step[1]
                    _seg_p = min(seg_end - 0.01, seg_start + _ratio * (seg_end - seg_start))
                else:
                    _seg_p = min(seg_end - 0.01, _seg_p + 0.02)
                progress(_seg_p, desc=status_msg.lstrip("⏳✅❌⏰ ").strip()[:40])
                yield f"[{idx}/{len(sizes)}] {status_msg}", list(gallery_urls)
                if status_msg.startswith(("✅", "❌", "⏰")):
                    break
        finally:
            _seg_pq.put(None)  # 通知该尺寸的 ws 线程退出

        # 抓这个尺寸的 image 输出，累积进 gallery_urls（Gallery 显示所有已完成图）
        try:
            hist = scail2_client.get_history(prompt_id)
            outs = scail2_client.extract_all_image_outputs(hist or {})
            for o in outs:
                all_outputs.append(o)
                gallery_urls.append(scail2_client.get_output_url(
                    o["filename"], o.get("subfolder", ""), o.get("type", "output")))
        except Exception as e:
            _log.error(f"[run_image] extract failed for {prompt_id}: {e}")

        progress(seg_end, desc=f"[{idx}/{len(sizes)}] {w}x{h} 完成")
        yield f"✅ [{idx}/{len(sizes)}] {w}x{h} done", list(gallery_urls)

    finished_at = datetime.now(timezone.utc)
    # manifest（复用 build_manifest，outputs 放进 reference_image 字段名不太合适，
    # 但 manifest schema 固定；文生图的输出记在 output 字段，多张取第一张 + 全量在 error 旁标注）
    primary = all_outputs[0] if all_outputs else None
    try:
        manifest = history.build_manifest(
            prompt_id=prompt_ids[0] if prompt_ids else "no-queue",
            started_at_iso=started_at.isoformat(),
            finished_at_iso=finished_at.isoformat(),
            duration_sec=int((finished_at - started_at).total_seconds()),
            preset=preset_name,
            reference_image="",
            drive_video="",
            prompt_text=prompt_text,
            status=final_status,
            cache_hit=False,
            output=primary,
            error=final_error,
            # zimage 文生图：seed + 实际跑的尺寸
            seed=seed_val,
            sizes=[f"{w}x{h}" for w, h in sizes],
        )
        # 文生图特有：记录全部尺寸输出 + 每尺寸 prompt_id
        manifest["outputs"] = all_outputs
        manifest["prompt_ids"] = prompt_ids
        history.write_manifest(manifest)
        _log.debug(f"[run_image] manifest written, {len(all_outputs)} outputs")
    except Exception as e:
        _log.error(f"[run_image] manifest write failed: {e}")

    progress(1.0 if final_status == "success" else 0,
                      desc="完成" if final_status == "success" else f"❌ {final_status}")
    yield f"✅ 全部完成，共 {len(all_outputs)} 张图", list(gallery_urls)















# --- 设置 tab：ComfyUI 地址 ---

def get_default_url():
    """获取 config 里的默认 ComfyUI URL（给 UI 的"恢复默认"和 placeholder 用）。"""
    return config.COMFY_BASE_URL


def save_and_test_url(url):
    """保存 URL 到运行时状态 + 立即测试连通性。返回状态消息给 UI。

    无论连通与否都保存（用户可能先填地址、稍后启动 ComfyUI）。
    """
    cleaned = scail2_client.set_base_url(url)
    if not cleaned:
        return "⚠️ URL 为空，请填写 ComfyUI 地址"
    ok, msg = scail2_client.check_connection(url=cleaned, timeout=5)
    return msg


def reset_to_default_url():
    """恢复到 config 默认 URL。返回 (默认URL, 状态消息) 给 UI（更新输入框 + 状态）。"""
    scail2_client.reset_base_url()
    default = config.COMFY_BASE_URL
    ok, msg = scail2_client.check_connection(url=default, timeout=5)
    return default, msg


def _run_full_health_check():
    """完整健康检查：连通性 + 系统 + 模型 + 自定义节点。返回 markdown 报告。"""
    from app import health_check
    report = health_check.check_health(timeout=8)
    return report.to_markdown()


def _build_settings_tab(theme_injector: gr.HTML | None = None):
    """⚙️ 设置 tab:ComfyUI 地址 + 快速测试 + 完整健康检查 + 主题切换。

    theme_injector 由 build_ui 顶部创建并传入,用于接收 _apply_theme() 的 <style>:root{}</style>
    动态注入。如果单独调用(测试场景)传 None,内部自建一个 fallback HTML,不崩。
    """
    if theme_injector is None:
        # 单独调用 _build_settings_tab() 的场景(测试 / 调试),建一个本地 injector
        theme_injector = gr.HTML(
        value=_apply_theme(_load_saved_theme()),
        visible=False,
        elem_id="theme-injector",
    )
    """⚙️ 设置 tab：ComfyUI 地址 + 快速测试 + 完整健康检查。"""

    gr.Markdown("## ⚙️ 系统设置")
    gr.Markdown("ComfyUI 地址运行时可改。默认 `127.0.0.1:8188`，可改成局域网/远程实例。")

    with gr.Row():
        url_input = gr.Textbox(
            label="ComfyUI URL",
            value=scail2_client.get_base_url(),
            placeholder="http://127.0.0.1:8188",
            scale=3,
            # Web Interface Guidelines §Forms: autocomplete="off" 阻止浏览器把这个
            # URL 输入框误识别为登录字段 (触发密码管理器弹窗). Gradio 6 通过 html_attributes
            # 透传原生 HTML 属性, 渲染成 <input autocomplete="off">.
            html_attributes={"autocomplete": "off"},
        )
        save_btn = gr.Button("保存并测试", variant="primary", scale=1)

    with gr.Row():
        reset_btn = gr.Button("恢复默认", variant="secondary")
        retest_btn = gr.Button("重新测试", variant="secondary")
        full_check_btn = gr.Button("🔍 完整健康检查", variant="secondary")

    status = gr.Textbox(label="快速连接状态", interactive=False, lines=2,
                        value="点「保存并测试」或「完整健康检查」")
    default_hint = gr.Markdown(f"_默认地址: `{config.COMFY_BASE_URL}`_")

    # 完整健康检查报告区
    gr.Markdown("---")
    health_report = gr.Markdown(
        "_点上方「🔍 完整健康检查」查看：连通性 + GPU/VRAM + 所需模型 + 所需自定义节点_"
    )

    # === 主题切换 ===
    gr.Markdown("---")
    gr.Markdown("## 🎨 主题")
    gr.Markdown("切换后即时生效 (毫秒级,无需刷新)。新增主题编辑 `app/presets/themes.json`。")

    theme_choices = [(t["name"], t["id"]) for t in _list_themes()]
    theme_radio = gr.Radio(
        choices=theme_choices,
        value=_load_saved_theme(),
        label="配色方案",
        elem_classes=["custom-radio"],
    )
    theme_desc = gr.Markdown(_get_theme_desc(_load_saved_theme()))

    def _on_theme_change(new_tid: str) -> tuple[str, str]:
        _save_theme(new_tid)  # 持久化用户选择,下次启动沿用
        return _apply_theme(new_tid), _get_theme_desc(new_tid)

    theme_radio.change(
        fn=_on_theme_change,
        inputs=[theme_radio],
        outputs=[theme_injector, theme_desc],
    )

    save_btn.click(fn=save_and_test_url, inputs=[url_input], outputs=[status])

    def _reset_and_update():
        default, msg = reset_to_default_url()
        return default, msg
    reset_btn.click(fn=_reset_and_update, outputs=[url_input, status])

    def _retest():
        ok, msg = scail2_client.check_connection(timeout=5)
        return msg
    retest_btn.click(fn=_retest, outputs=[status])

    full_check_btn.click(fn=_run_full_health_check, outputs=[health_report])

    return url_input, status


# --- 启动期自检 ---

def _preflight():
    msgs = []
    ok, msg = scail2_client.check_connection(timeout=3)
    msgs.append(msg)
    for name in [w["name"] for w in config.list_workflows()]:
        p = config.workflow_path(name)
        msgs.append(f"preset {name}: {'OK' if p.exists() else f'MISSING ({p})'}")
    msgs.append(f"params.json: {'OK' if config.PARAMS_FILE.exists() else 'MISSING'}")
    msgs.append(f"RUNS_DIR: {config.RUNS_DIR} ({'OK' if config.RUNS_DIR.exists() else 'MISSING'})")
    msgs.append(f"GRADIO = http://{config.GRADIO_HOST}:{config.GRADIO_PORT}")
    return "\n".join(msgs)


# --- UI 构造 ---

def _update_est(drive_path, per_seg=81, pre_drop=5, max_segments=0):
    """根据驱动视频帧数估算段数，返回 markdown 提示。

    用 kwargs 而非位置参数：调用方按字段有无传参，缺哪个用默认值，不会错位。
    """
    if not drive_path:
        return "**预估段数**: 上传驱动视频后显示"
    frames = get_video_frames(drive_path)
    if frames is None:
        return f"**预估段数**: 读取帧数失败 ({drive_path})"
    auto = estimated_segments(frames, per_seg, pre_drop, max_segments=0)
    est = estimated_segments(frames, per_seg, pre_drop, max_segments=max_segments)
    net = max(1, int(per_seg) - int(pre_drop))
    if max_segments and max_segments > 0:
        if est < auto:
            return f"**预估段数**: {est} (已限制)  \n(驱动视频 {frames} 帧 / 每段 {per_seg} / pre-drop {pre_drop} / 净每段 {net} / 限制 ≤ {max_segments}, 自动算 {auto})"
        else:
            return f"**预估段数**: {est}  \n(驱动视频 {frames} 帧 / 每段 {per_seg} / pre-drop {pre_drop} / 净每段 {net} / 限制 ≤ {max_segments})"
    return f"**预估段数**: {est} (无限制)  \n(驱动视频 {frames} 帧 / 每段 {per_seg} / pre-drop {pre_drop} / 净每段 {net})"


def _output_kind(preset_cfg) -> str:
    """根据 preset 配置推导输出类型: image | video | audio。

    优先级: output_kind 字段 > category 字段 > 默认 video (向后兼容 sca12 类老 preset)。
    视频/音频 preset 走 _media_to_html 的非图片分支; 区别在 _media_to_html 内部用扩展名判定
    (mp4/mov/webm/gif -> video, mp3/wav/flac -> audio, 其它走 file-fallback banner)。
    """
    ok = preset_cfg.get("output_kind")
    if ok in ("image", "video", "audio"):
        return ok
    cat = preset_cfg.get("category")
    if cat == "image":
        return "image"
    if cat == "audio":
        return "audio"
    return "video"


def _is_image_preset(preset_cfg) -> bool:
    """preset 是文生图类（输出 image）。保留旧 API, 内部走 _output_kind。"""
    return _output_kind(preset_cfg) == "image"



# [迁移 2026-07-21] status 解析的 5 个函数 + 2 个模块常量已抽到 app.services.status.
from app.services.status import (
    _extract_status_kind,
    _extract_step_progress,
    _phase_from_status,
    _format_elapsed,
    _failure_hint,
    _STEP_PROGRESS_RE,
    _LIVE_RE,
)


def _now_ts():
    """返回当前时间戳 (秒), 给 status_bar 算已耗时。"""
    import time
    return time.monotonic()


def _render_status_html(state, msg='', elapsed_str='', task_list=None):
    """
    state in {idle, running, success, failure, timeout}: 决定颜色 + 图标。
    elapsed_str: 已耗时字符串(例如 ‘00:42’),使用在 running/最终态。
    task_list: list[dict],每个 dict = {text, status, detail};
        status in {‘done’, ‘current’, ‘pending’, ‘failed’}。
        传了 -> 渲服成 checklist, 主区域不再依赖 msg。
        不传 -> 退回到旧版单条 msg (idle / 初始化路径)。
    msg: 最新一条 status_msg (含 emoji 前缀)。task_list 渲服时主区域不用 msg,
        但 failure/timeout 时仍传给 _failure_hint 查具体下一步建议。

    review 2026-07-21 进度区域重构:
        不再渲服 ‘’60%’ 百分比胶囊 —— 那是 gr.Progress 在作品预览那条
        进度条上已经显示过的信息, 重复。改渲服成 task 清单, 用户能看见
        ‘现在做哪一步 / 前面几步完成没’, 进度条归作品预览独占。
    review P2 副标题 2: 让’运行中’成为全局主状态, 状态感更强。
    Phase 5: failure / timeout 时附加 _failure_hint (具体下一步建议), 不只报错。
    """
    icons = {'idle': chr(0x23F8), 'running': chr(0x1F504), 'success': chr(0x2705), 'failure': chr(0x274C), 'timeout': chr(0x23F0)}
    state_cn = {'idle': '等待运行', 'running': '正在运行', 'success': '已完成', 'failure': '运行失败', 'timeout': '运行超时'}
    icon = icons.get(state, chr(0x2022))
    label = state_cn.get(state, state)
    header_html = (
        '<span class="run-status-icon">' + icon + '</span>'
        + '<span class="run-status-label">' + label + '</span>'
    )
    elapsed_html = ('<span class="run-status-elapsed">' + chr(0x23F1) + ' ' + elapsed_str + '</span>') if elapsed_str else ''
    if task_list:
        task_icons = {'done': chr(0x2713), 'current': chr(0x25C9), 'pending': chr(0x25CB), 'failed': chr(0x2717)}
        items = []
        for t in task_list:
            if isinstance(t, dict):
                s = t.get('status') or 'pending'
                text = t.get('text') or ''
                detail = t.get('detail') or ''
            else:
                s = 'pending'
                text = str(t)
                detail = ''
            ti = task_icons.get(s, chr(0x2022))
            detail_html = (' <span class="run-status-task-detail">' + detail + '</span>') if detail else ''
            cls = 'run-status-task run-status-task-' + s
            items.append(
                '<li class="' + cls + '">'
                + '<span class="run-status-task-icon">' + ti + '</span>'
                + '<span class="run-status-task-text">' + text + '</span>'
                + detail_html
                + '</li>'
            )
        body_html = '<ul class="run-status-tasks">' + ''.join(items) + '</ul>'
    else:
        # 旧版单条 msg (idle / 初始化), review P3-9: ‘’ 分隔符 + 截断到 60 字
        clean = msg or ''
        if clean:
            for prefix in (chr(0x23F3), chr(0x2705), chr(0x274C), chr(0x23F0)):
                if clean.startswith(prefix):
                    clean = clean[len(prefix):].strip()
                    break
            if len(clean) > 60:
                clean = clean[:60] + chr(0x2026)
        sep = ' · ' if clean.strip() else ''
        body_html = (
            '<span class="run-status-sep">' + sep + '</span>'
            + '<span class="run-status-msg">' + clean + '</span>'
        )
    hint_html = ''
    if state in ('failure', 'timeout'):
        hint = _failure_hint(msg)
        if hint:
            hint_html = '<div class="run-status-hint">' + hint + '</div>'
    return (
        '<div class="run-status-bar run-status-' + state + '">'
        + header_html
        + elapsed_html
        + body_html
        + hint_html
        + '</div>'
    )

def _create_one_input(spec):
    """创建单个输入组件 + 紧跟的辅助元素（预览/随机按钮）。

    返回 (主组件, 缩略图组件 或 None) —— 缩略图组件对 file:image / file:video
    存在,其它 spec 返回 None。组件构造即注册到当前 Blocks 上下文,不调 .render()。

    调用方把缩略图组件收集到与 inputs 平行的列表里,统一喂给 ex_btn.click /
    last_btn.click / wf_radio.change,以及初始渲染时的默认缩略图。
    """
    from app import prompts as prompts_mod
    typ = spec["type"]
    comp = _build_input_component(spec)
    preview_comp = None
    if typ == "file:image":
        with gr.Row():
            preview_comp = gr.Image(label="缩略图", height=180, interactive=False, show_label=False)
            comp.change(fn=lambda p: p if p else None, inputs=[comp], outputs=[preview_comp])
    elif typ == "file:video":
        with gr.Row():
            preview_comp = gr.Video(label="预览", height=180, interactive=False, autoplay=False, show_label=False)
            comp.change(fn=lambda p: p if p else None, inputs=[comp], outputs=[preview_comp])
    elif typ == "prompt_pool":
        with gr.Row():
            rand_btn = gr.Button("🎲 随机提示词", variant="secondary", size="sm")
            rand3_btn = gr.Button("🎲 随机3条", variant="secondary", size="sm")
            rand_btn.click(fn=lambda: prompts_mod.random_prompt(), outputs=[comp])
            rand3_btn.click(
                fn=lambda: "\n---\n".join(prompts_mod.random_prompts(n=3)),
                outputs=[comp],
            )
    return comp, preview_comp

def _set_initial_component_value(component, value):
    """Apply a preset.example value using Gradio's constructor-time pipeline."""
    from gradio.data_classes import BaseModel
    from gradio.processing_utils import move_files_to_cache

    if isinstance(component, list):
        for child, child_value in zip(component, value):
            _set_initial_component_value(child, child_value)
        return
    initial_value = component.postprocess(value)
    if isinstance(initial_value, BaseModel):
        initial_value = initial_value.model_dump()
    component.value = move_files_to_cache(
        initial_value, component, postprocess=True, keep_in_cache=True
    )


# [迁移 2026-07-21] _save_last_run / _load_last_run 已抽到 app.services.persistence.
from app.services.persistence import _save_last_run, _load_last_run


def _open_output_dir_action() -> str:
    """点📂按钮:打开 ComfyUI 输出目录到系统文件管理器(Win 用 explorer)。"""
    import platform
    path = str(config.COMFY_OUTPUT_DIR)
    try:
        config.COMFY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        sys_name = platform.system()
        if sys_name == "Windows":
            subprocess.Popen(["explorer", path])
        elif sys_name == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return f"已打开: {path}"
    except Exception as e:
        return f"打开失败 ({type(e).__name__}): {e}"


def _comfy_status_text() -> str:
    """返回 ComfyUI 实时连接状态的 markdown。"""
    try:
        ok, _msg = scail2_client.check_connection(timeout=2)
    except Exception:
        ok = False
    dot = chr(0x1F7E2) if ok else chr(0x1F534)  # 绿色 / 红色圆点
    return f"ComfyUI: {dot} `{scail2_client.get_base_url()}`"


def _open_comfy_output_dir() -> str:
    """Open the ComfyUI output directory in the OS file explorer.

    Returns a status string describing the result (suitable for display
    in the workflow sidebar). The button replaces the removed history tab
    (2026-07-18 redesign) as the way to find generated files.

    Behavior:
      - config.COMFY_OUTPUT_DIR exists: opens it via os.startfile
        (server-side call, only effective when WebUI is launched locally --
        which is the supported deployment per project AGENTS.md).
      - directory missing: returns an error message; does NOT call
        os.startfile (avoids FileNotFoundError / Windows error dialog).
    """
    path = config.COMFY_OUTPUT_DIR
    if not path.exists():
        return '❌ 输出目录不存在： ' + str(path)
    try:
        _os.startfile(str(path))
    except Exception as e:
        return '❌ 打开输出目录失败： ' + str(e)
    return '✅ 已在文件管理器中打开： ' + str(path)


_CATEGORY_ICON = {"video": chr(0x1F3AC), "image": chr(0x1F5BC) + chr(0xFE0F),
                  "audio": chr(0x1F50A), "3d": chr(0x1F9CA), "other": chr(0x1F4E6)}

# [迁移 2026-07-21] _FILE_ROUTE_PREFIX / _media_ext_from_url / _media_to_html
# 已抽到 app.services.media. 保留 _FILE_ROUTE_PREFIX 在本模块的可见性
# (scail2_app.py 内部的 _versioned_preview_url 等仍引用它).
from app.services.media import (
    _FILE_ROUTE_PREFIX,
    _media_ext_from_url,
    _media_to_html,
)


def _versioned_preview_url(src: Path) -> str | None:
    """Return a repo-local Gradio file URL keyed by the current bytes."""
    try:
        rel = src.relative_to(config.REPO_ROOT)
    except ValueError:
        return None
    import hashlib
    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    route = _FILE_ROUTE_PREFIX + str(rel).replace(chr(92), "/")
    return f"{route}?v={digest}"


def _category_icon(cat: str) -> str:
    return _CATEGORY_ICON.get(cat, chr(0x1F4E6))


def _wf_label(w: dict) -> str:
    """build_ui nav Radio label. emoji + display_name only.

    review P0-2 (2026 July 17): the trailing `image` / `video` / `audio` suffix
    was redundant noise; emoji already conveys the category. Also pushed each
    Radio row from single-line to two-line (60px height). Suffix removed.
    """
    cat = w.get("category", "other")
    icon = _category_icon(cat)
    return f"{icon} {w['display_name']}"



def _yield_run_stream(
    run_fn,
    preset_name: str,
    vals: tuple,
    *,
    output_kind: str,
    on_status_done=None,
):
    """包装 run_fn 流式输出 -- 纯生成器逻辑(不依赖 Gradio 组件引用)。

    run_fn(preset_name, *vals) 是个 generator,yield (status_msg, media) 元组。
    这里把它包成面向 Gradio 输出的 6-tuple 流:
      (status_text, media_html, error_update, re_run_visible_update,
       open_dir_msg_update, last_media)

    Args:
        on_status_done: 可选回调(status_msg, vals)。当某条 status 以
            ✅ 开头时调用 -- 调用方用来触发 _save_last_run / 显示 last_btn。

    关键行为(对应 zimage 跑完图不显示的回归):
        run_fn 自然结束后,最后一次 yield 仍保留最后生成的 media(若有),
        不重置成 None -- 否则前端 output_box 会被 _media_to_html(None, ...)
        覆盖成等待结果占位,用户看不到刚生成的图/视频。
    """
    log: list[str] = []
    last_media = None

    try:
        for status_msg, media in run_fn(preset_name, *vals):
            log.append(status_msg)
            if media:
                last_media = media

            err_visible = False
            err_html = ""
            if status_msg.startswith(chr(0x274C)):
                err_visible = True
                inner = status_msg.lstrip(chr(0x274C)).strip()
                err_html = ("<div class='error-banner-inner'>"
                            f"<b>上次运行失败</b><br>{inner}</div>")
            elif status_msg.startswith(chr(0x23F0)):
                err_visible = True
                inner = status_msg.lstrip(chr(0x23F0)).strip()
                err_html = ("<div class='error-banner-inner'>"
                            f"<b>运行超时</b><br>{inner}</div>")

            show_re_run = status_msg.startswith(chr(0x2705))
            if show_re_run and on_status_done is not None:
                on_status_done(status_msg, vals)

            yield (
                chr(10).join(log[-12:]),
                _media_to_html(media, output_kind),
                gr.update(value=err_html, visible=err_visible),
                gr.update(visible=show_re_run),
                gr.update(value="", visible=False),
                last_media,
            )
    except Exception as exc:
        _log.exception("_yield_run_stream 异常: %s", exc)
        log.append(chr(0x274C) + " " + repr(exc))
        yield (
            chr(10).join(log[-12:]),
            _media_to_html(last_media, output_kind),
            gr.update(value=f"<div class='error-banner-inner'><b>运行异常</b><br>{exc!r}</div>", visible=True),
            gr.update(visible=False),
            gr.update(value="", visible=False),
            last_media,
        )

    yield (
        chr(10).join(log[-12:]),
        _media_to_html(last_media, output_kind),
        gr.update(value="", visible=False),
        gr.update(visible=False),
        gr.update(value="", visible=False),
        last_media,
    )


def _render_workflow_form(preset_name):
    """渲染单个 preset 的卡片式表单。

    build_ui 会把所有 preset 一次性预渲染到 gr.Group 里,通过 visibility 切换。
    切 preset 时组件不被销毁,表单状态由 Gradio 自动保留。

    结构:
    - 工作流标题 + 简介
    - [加载示例 / 加载上次参数] 按钮(同 row)
    - 输入素材 / 基础参数 / 高级参数折叠
    - 段数预估(仅视频类)
    - 运行日志(折叠,默认收起)
    - 错误高亮(失败时显示)
    - 运行 + 再来一次(row)
    - 生成结果(HTML)
    - 打开 ComfyUI 输出目录
    """
    from functools import partial
    preset_cfg = config.preset_config(preset_name)
    output_kind = _output_kind(preset_cfg)
    is_image = output_kind == "image"
    specs = preset_cfg["user_facing_inputs"]
    _initial_form_values = example_to_form_values(preset_name)
    _initial_values_by_spec = []
    _flat_index = 0
    for _spec in specs:
        _value_count = 2 if _spec.get("type") == "int_random" else 1
        _values = _initial_form_values[_flat_index:_flat_index + _value_count]
        _initial_values_by_spec.append(_values if _value_count == 2 else _values[0])
        _flat_index += _value_count

    # [顶部] 工作流标题 + 简介
    # 用 ## (h2): 全局 h1=app 标题, h2=工作流, section-header=form 小节, 三级层级清晰。
    # 之前用 ### (h3) 跳过了 h2 层级, 且 h3 颜色是 --text-secondary (灰) 比下面的
    # section-header (primary 白) 还暗, 副标题比标题醒目 (review 2026-07-17 排版审计)。
    gr.Markdown(
        f"## {preset_cfg.get('display_name', preset_name)}\n"
        f"<span style='color:var(--text-muted)'>{preset_cfg.get('description', '')}</span>"
    )

    # ===== 第四阶段 §A：两栏工作台布局 =====
    # with gr.Row(equal_height=True) 包左右两栏 (review 2026-07-17: 改 True 让两栏等高):
    #   左控制栏 gr.Column(scale=4): basic 输入 + 高级参数 + 段数预估 + 示例按钮 + 🚀 开始运行
    #   右预览栏 gr.Column(scale=7): 📜 运行日志 + 错误条 + 结果区 + 🔁 再来 + 打开输出目录
    # 组件创建顺序保证: 左栏全部组件 → 右栏全部组件 (事件绑定在两栏关闭后才做,
    # 引用的都是已存在的组件对象,不受布局影响)。
    # 按 spec index 存 component —— 同一 node 上多 spec (例如 469 同时挂
    # file:video + int frame_load_cap) 各自独立, dict-by-node_id 会把前一个覆盖。
    # 原先的 dict 实现在 sca12_motion 上崩: spec[4] (469 file:video) 被 spec[5]
    # (469 int) 覆盖, flat[4] 变成 int, example_to_form_values 返回的路径字符串
    # 落到 gr.Number 里 → TypeError "type str doesn't define __round__ method"。
    spec_to_comp: list = [None] * len(specs)
    # 缩略图组件与 spec_to_comp 同长度对齐 —— file:image / file:video spec 有 gr.Image/gr.Video,
    # 其它 spec 为 None。ex_btn / last_btn / wf_radio 三条加载路径会把缩略图一起更新,
    # 否则用户切到 Klein / LTX i2v 后只看到空上传框,没有任何视觉提示。
    spec_to_preview: list = [None] * len(specs)
    basic_specs = [s for s in specs if s.get("tier", "basic") == "basic"]
    advanced_specs = [s for s in specs if s.get("tier") == "advanced"]

    # review 2026-07-17 排版审计: 改 equal_height=True。
    # 原 False 让左右子栏不等高, 运行按钮 (左) 和输出区 (右) Y 坐标飘 —— 首次成功后
    # re_run_btn 出现, 右栏长一截, 运行按钮原本对齐输出区中部, 之后错位。True 让两栏
    # 顶部对齐, 运行按钮锚定左栏底部, 不随右栏内容增长而漂移。
    with gr.Row(equal_height=True):
        # ============ 左控制栏 ============
        # scale=4 + min_width=380:保证表单控件(尤其是带 info 的输入)有足够宽度,
        # 而右预览栏用 scale=7 拿走剩余 64% → review P0「预览自然扩展」。
        with gr.Column(scale=4, min_width=380):
            # P2 顶部运行状态条 (review 副标题 2: 让运行中成为全局主状态)
            #   状态: idle / running / success / failure / timeout
            #   内容: 图标 + 状态中文 + 最新一条 status_msg + 已耗时 (mm:ss)
            # 默认 idle, 运行中由 _run_and_format 持续 yield 更新。
            status_bar = gr.HTML(
                value=_render_status_html('idle', '点击下方按钮开始, 或先点上方「加载示例素材」'),
                elem_classes=["run-status-container"],
            )
            # [输入组件]
            # basic 组件按 user_facing_inputs 原始顺序渲染(不拆 file/param 两组),这样作者在
            # params.json 里把"抠图词"排在对应上传文件后面,UI 上就紧跟在一起 —— 例如
            # 参考图(30) → 参考图抠图词(362) → 驱动视频(369) → 驱动视频抠图词(348)。
            # advanced 组件仍折叠进"🔧 高级参数"。
            # P4 卡片套娃 flatten —— review 副标题 1:
            # 原结构是 step-card + card-core 双层卡片(两个边框 + 双层阴影),
            # 视觉上『套娃』感强。这里去掉 card-core, 只保留 section-header 风格分隔;
            # 主结果区(右栏 result-area)和系统级 Group(如 settings) 仍保留卡片。
            if basic_specs:
                with gr.Group(elem_classes=["step-card"]):
                    gr.Markdown("**① 输入素材**", elem_classes=["section-header"])
                    for spec_idx, spec in enumerate(specs):
                        if spec.get("tier", "basic") != "basic":
                            continue
                        comp, preview = _create_one_input(spec)
                        _initial_value = _initial_values_by_spec[spec_idx]
                        _set_initial_component_value(comp, _initial_value)
                        if preview is not None and _initial_value:
                            _set_initial_component_value(preview, _initial_value)
                        # int_random 返回 [Checkbox, Number] 两组件, 其他返回单组件
                        spec_to_comp[spec_idx] = comp
                        spec_to_preview[spec_idx] = preview

            if advanced_specs:
                with gr.Accordion("🔧 高级参数(一般不用改)", open=False, elem_classes=["custom-accordion"]):
                    for spec_idx, spec in enumerate(specs):
                        if spec.get("tier") != "advanced":
                            continue
                        comp, preview = _create_one_input(spec)
                        _initial_value = _initial_values_by_spec[spec_idx]
                        _set_initial_component_value(comp, _initial_value)
                        if preview is not None and _initial_value:
                            _set_initial_component_value(preview, _initial_value)
                        spec_to_comp[spec_idx] = comp
                        spec_to_preview[spec_idx] = preview

            # 重建扁平 inputs 列表 (int_random 拆 2 个, 其他 1 个)。
            # 按 spec index 严格对齐 —— 同一 node 上的多 spec 也各占自己的 flat 位置,
            # example_to_form_values / run_workflow 都是 spec 序遍历, 这里必须保证
            # flat[i] 对应 specs[i] (而不是按 node_id 拼接 —— 会造成重复或丢失)。
            inputs = []
            for spec_idx, comp in enumerate(spec_to_comp):
                if comp is None:
                    # 防御性: 某个 spec 没创建对应组件不该发生, 但跳过也别让整页崩
                    continue
                if isinstance(comp, list):
                    inputs.extend(comp)
                else:
                    inputs.append(comp)
            # 缩略图组件与 inputs 同顺序对齐 —— 紧跟每个 file spec 的 gr.File 之后,
            # 收集到的预览组件数 = file spec 数, 每个 spec_to_preview[i] 不为 None 时
            # 占据一个 inputs 之后的槽位。
            preview_components: list = [c for c in spec_to_preview if c is not None]
            # preview_components[j] 的 .value 应该等于 inputs[对应 flat index] 的当前值。
            _preview_value_at: list[int] = []
            _running_flat = 0
            for spec_idx, comp in enumerate(spec_to_comp):
                if comp is None:
                    continue
                step = 2 if isinstance(comp, list) else 1
                if spec_to_preview[spec_idx] is not None:
                    _preview_value_at.append(_running_flat)
                _running_flat += step
            # 段数预估(仅视频类 preset)
            if output_kind == "video":
                _drive_idx = next((i for i, s in enumerate(specs) if s["type"] == "file:video"), None)
                _per_seg_idx = next((i for i, s in enumerate(specs) if str(s.get("node_id")) == "367"), None)
                _pre_drop_idx = next((i for i, s in enumerate(specs) if str(s.get("node_id")) == "464"), None)
                _max_idx = next((i for i, s in enumerate(specs) if str(s.get("node_id")) == "479"), None)
                if _drive_idx is not None:
                    est_segments = gr.Markdown("📊 **预估段数**: 上传驱动视频后显示")
                    _est_inputs = [inputs[_drive_idx]]
                    if _per_seg_idx is not None:
                        _est_inputs.append(inputs[_per_seg_idx])
                    if _pre_drop_idx is not None:
                        _est_inputs.append(inputs[_pre_drop_idx])
                    if _max_idx is not None:
                        _est_inputs.append(inputs[_max_idx])
                    for _trigger in _est_inputs:
                        _trigger.change(fn=_update_est, inputs=_est_inputs, outputs=[est_segments])

            # [加载示例 / 加载上次参数]
            has_example = bool(preset_cfg.get("example"))
            last_run_path = config.LAST_RUN_DIR / f"{preset_name}.json"
            has_last = last_run_path.exists()

            with gr.Row():
                ex_btn = (gr.Button("📥 加载示例素材", variant="secondary", size="sm", scale=1)
                          if has_example else None)
                last_btn = gr.Button(
                    "📂 加载上次成功参数",
                    variant="secondary",
                    size="sm",
                    scale=1,
                    visible=has_last,
                )

            # [运行] 唯一绝对主操作按钮 (左栏底部)
            run_btn = gr.Button(
                "🚀 开始运行", variant="primary", size="md",
                elem_classes=["btn-run-primary"],
            )

        # ============ 右作品预览栏 ============
        # scale=7:拿主区 ~64% 宽度,在 1280px 视口下约 687px,1920px 视口下约 1095px
        # —— 直接把右侧空白吃掉,主图成为真正主角 (review P0 / 副标题 3)。
        # min_width=460 保证极窄窗口下预览区不会塌缩。
        with gr.Column(scale=7, min_width=460):
            # [示例预览 → 输出区默认值] (review 2026-07-11)
            # 原来为了避免示例预览卡和生成结果区重复, 刚刚把预览卡整个删了.
            # 但默认参数 = example, 跑出来就是 example 里的那张图, “让别人直接看到”
            # (看到这个工作流能产出什么) 是个真实需求. 重新表达:
            #   - 不再独立“示例预览”卡片
            #   - 直接把 example.preview_image / preview_video 填进 output_box 作为默认值
            #   - 跑了之后 _run_and_format 会用实际生成结果覆盖这个默认值
            #   - 默认值上有个小说明“示例效果”, 跑完后被覆盖不影响

            # [生成结果] 是右栏顶部第一块 (review 2026-07-14).
            # 原来运行日志 Accordion 在 output_box 上方, 它默认收起 (~40px) 跟左栏
            # status_bar (44px+margin) 高度不同, 把两栏下方内容推到不同 Y 坐标 → 顶部不齐.
            # 现在把运行日志移到最底部 (它默认收起, 不是首屏焦点), 让右栏顶部直接是预览图,
            # 跟左栏顶部的 status_bar 形成「状态条(小) + 预览图(大)」的有意图不对称.

            # [错误高亮] 默认隐藏 (output_box 之下)
            error_box = gr.HTML(value="", visible=False, elem_classes=["error-banner"])

            # [生成结果] -- 默认填 example 的 preview, 跑了之后被覆盖.
            def _resolve_preview_path(raw):
                """\u89e3\u6790 example \u9884\u89c8\u8def\u5f84\u4e3a browser \u53ef\u8bbf\u95ee URL.
                - http(s):// URL: \u539f\u6837\u8fd4\u56de
                - \u9879\u76ee\u5185\u8def\u5f84 (\u7edd\u5bf9\u6216 app/...): \u8f6c\u6210 /file=... \u8def\u7531
                  (Gradio 6 \u4e0d\u5141\u8bb8\u5916\u90e8\u672c\u5730\u8def\u5f84, /file= \u662f\u552f\u4e00\u53ef\u7528\u7684\u9759\u6001\u670d\u52a1\u65b9\u5f0f)
                - \u8fd4\u56de None: \u8c03\u7528\u65b9\u4f1a\u8df3\u8fc7\u9884\u89c8, \u4ec5\u663e\u793a\u5360\u4f4d\u7b26
                """
                if not raw: return None
                if raw.startswith(("http://", "https://")):
                    return raw
                # \u672c\u5730\u8def\u5f84: \u62c6\u51fa\u76f8\u5bf9 REPO_ROOT \u7684\u8def\u5f84, \u62fc /file= URL
                src = Path(raw) if not Path(raw).is_absolute() else Path(raw)
                if not src.is_absolute():
                    src = config.REPO_ROOT / src
                return _versioned_preview_url(src)
            _ex_for_default = preset_cfg.get("example") or {}
            _pv_video_raw = _ex_for_default.get("preview_video")
            _pv_image_raw = _ex_for_default.get("preview_image")
            _pv_audio_raw = _ex_for_default.get("preview_audio")
            if _pv_video_raw:
                _pv_url = _resolve_preview_path(_pv_video_raw)
                _default_output_html = "<div class='result-area-default' style='padding:8px'>\n<video controls style='max-width:100%;border-radius:var(--radius-md)'>\n<source src='SRC_PLACEHOLDER'/></video>\n<div class='result-area-caption' style='font-size:12px;color:var(--text-muted);margin-top:6px;text-align:center'>📸 示例效果 (默认参数对应的结果)</div>\n</div>".replace("SRC_PLACEHOLDER", _pv_url)
            elif _pv_image_raw:
                _pv_url = _resolve_preview_path(_pv_image_raw)
                _default_output_html = "<div class='result-area-default' style='padding:8px'>\n<img src='SRC_PLACEHOLDER' style='max-width:100%;border-radius:var(--radius-md)'/>\n<div class='result-area-caption' style='font-size:12px;color:var(--text-muted);margin-top:6px;text-align:center'>📸 示例效果 (默认参数对应的结果)</div>\n</div>".replace("SRC_PLACEHOLDER", _pv_url)
            elif _pv_audio_raw:
                _pv_url = _resolve_preview_path(_pv_audio_raw)
                _default_output_html = "<div class='result-area-default' style='padding:8px'>\n<audio controls preload='metadata' style='width:100%;max-width:480px'>\n<source src='SRC_PLACEHOLDER'/></audio>\n<div class='result-area-caption' style='font-size:12px;color:var(--text-muted);margin-top:6px;text-align:center'>📸 示例效果 (默认参数对应的结果)</div>\n</div>".replace("SRC_PLACEHOLDER", _pv_url)
            else:
                _default_output_html = "<div style='color:var(--text-faint);padding:20px'>运行后这里显示结果</div>"
            output_box = gr.HTML(
                value=_default_output_html,
                elem_classes=["result-area"],
                label="生成结果",
            )
            # [次级操作] 🔁 用相同参数再来 (视觉降级, 不抢主按钮焦点)
            re_run_btn = gr.Button(
                "🔁 用相同参数再来",
                variant="secondary",
                size="md",
                visible=False,
                elem_classes=["btn-run-secondary"],
            )

            # [打开输出目录]
            open_dir_msg = gr.Markdown(value="", visible=False)
            open_dir_btn = gr.Button("📂 打开 ComfyUI 输出目录", variant="secondary", size="sm")

            # [运行日志] 折叠(默认收起,跑起来自动展开) —— 放在最底部 (review 2026-07-14).
            # 见上方注释: 移到 output_box 下方, 让右栏顶部直接是预览图.
            with gr.Accordion("📜 运行日志", open=False, elem_classes=["custom-accordion"]):
                status_box = gr.Textbox(
                    value="等待运行,或点上方「加载示例素材」",
                    label="状态",
                    interactive=False,
                    lines=4, max_lines=10,
                )
    # === 事件绑定 ===
    has_image_sizes = any(spec.get("type") == "image_sizes" for spec in preset_cfg.get("user_facing_inputs", []))
    run_fn = run_image_workflow if has_image_sizes else run_workflow
    #
    # 运行按钮的两个状态 update:
    #   _RUN_BTN_RUNNING —— 切到 "⏳ 正在运行…" + .is-running + 禁用 → spinner / pulse 立刻出来
    #   _RUN_BTN_RESTING —— 还原 "🚀 开始运行" + .btn-run-primary + 可点
    # Gradio .click() 触发 generator 时,每次 yield 都会把 update 推给对应 output。
    # generator 自然结束(StopIteration)→ finally 跑完 → 控制流继续往下走 → 最后一次
    # yield RESTING,前端按钮立刻从 "正在运行…" 切回 "开始运行"。
    # 设计要点(为什么不在 _render_workflow_form 外层包 wrapper):
    #   wrapper 会破坏 generator 与 Gradio streaming 协议,改 Inner 实现的成本远高于在
    #   同一函数内做状态收尾。
    _RUN_BTN_RUNNING = gr.update(
        value=chr(0x23F3) + " " + "正在运行…",
        elem_classes=["btn-run-primary", "is-running"],
        interactive=False,
    )
    _RUN_BTN_RESTING = gr.update(
        value=chr(0x1F680) + " " + "开始运行",
        elem_classes=["btn-run-primary"],
        interactive=True,
    )

    def _run_and_format(*vals):
        """包装 run_fn:累积日志、错误高亮、跑完存 last_run。

        yields: (status_text, media_html, error_update, re_run_visible_update,
                 open_dir_msg_update, run_btn_update)
        run_btn_update 是第 6 项 -- 每次 yield 都带上按钮态。

        业务逻辑(log 累积 / 错误高亮 / media 保留)在 _yield_run_stream,
        这里只处理 Gradio 组件引用:按钮 interactive 切换 + last_run 持久化。
        """
        run_btn.interactive = False
        re_run_btn.visible = False
        error_box.visible = False
        open_dir_msg.visible = False
        # P2: 切到 running 状态 + 记录开始时间 (elapsed timer)
        status_bar.value = _render_status_html('running', '', '00:00')
        _run_start_ts = _now_ts()

        def _on_done(_status_msg, _vals):
            _save_last_run(preset_name, _vals)
            last_btn.visible = True

        log_text = ""
        last_media = None
        # review 2026-07-21: 进度区域用 task_list 取代 ‘’60%’ 胶囊; gr.Progress 单独管进度条。
        # task_list 在循环外声明, 跨 yield 累积, 直到 run 结束。
        task_list: list[dict] = []
        try:
            for log_text, media_html, err_upd, re_run_upd, open_dir_upd, last_media in _yield_run_stream(
                run_fn=run_fn,
                preset_name=preset_name,
                vals=vals,
                output_kind=output_kind,
                on_status_done=_on_done,
            ):
                # _yield_run_stream 第一项是 chr(10).join(log[-12:]) (拼接日志),
                # 状态条 / task_list 只关心最后一条 single msg (最新一行).
                status_msg = log_text.split(chr(10))[-1] if log_text else ""
                # P2: 根据 status_msg 前缀切换状态条 (✅→success, ❌/⏰→failure/timeout, 其它→running)
                _state = 'running'
                if status_msg.startswith(chr(0x2705)):
                    _state = 'success'
                elif status_msg.startswith(chr(0x274C)):
                    _state = 'failure'
                elif status_msg.startswith(chr(0x23F0)):
                    _state = 'timeout'
                _elapsed = _format_elapsed(_now_ts() - _run_start_ts)
                # review 2026-07-21: 把 status_msg 解析成 phase action, 累积 task_list
                # (live_update 只刷新当前 task 的 detail, 不开新行; 长轮询刷几十条不会爆)
                _action, _phase_text, _detail = _phase_from_status(status_msg)
                if _action == 'new_task':
                    # 之前 current 的 task 收尾
                    if task_list and task_list[-1]['status'] == 'current':
                        task_list[-1]['status'] = 'done'
                    task_list.append({'text': _phase_text, 'status': 'current', 'detail': ''})
                elif _action == 'live_update':
                    if task_list:
                        task_list[-1]['detail'] = _detail
                elif _action == 'task_done':
                    if task_list and task_list[-1]['status'] == 'current':
                        task_list[-1]['status'] = 'done'
                elif _action in ('task_failed', 'task_timeout'):
                    if task_list and task_list[-1]['status'] == 'current':
                        task_list[-1]['status'] = 'failed'
                _status_bar_update = gr.update(value=_render_status_html(_state, status_msg, _elapsed, task_list))
                yield (
                    log_text,
                    media_html,
                    err_upd,
                    re_run_upd,
                    open_dir_upd,
                    _RUN_BTN_RUNNING,
                    _status_bar_update,
                )
        finally:
            run_btn.interactive = True

        # P2: 根据最后一条 status_msg 决定状态条终态 (log_text 是拼接 log,
        # 真正的 latest single msg 是最后一行)
        _latest = log_text.split(chr(10))[-1] if log_text else ""
        _final_state = 'idle'
        if _latest.startswith(chr(0x2705)):
            _final_state = 'success'
        elif _latest.startswith(chr(0x274C)):
            _final_state = 'failure'
        elif _latest.startswith(chr(0x23F0)):
            _final_state = 'timeout'
        elif log_text:
            # 跑完但 latest 末尾没有特殊前缀 (异常退出), 仍归 success 让按钮可见
            _final_state = 'success'
        _final_elapsed = _format_elapsed(_now_ts() - _run_start_ts)
        # review 2026-07-21: 终态也带上 task_list (用户能看到完整过程),
        # 失败/超时 task 还保留最后一个 failed 状态作为线索。
        _final_status_bar = gr.update(value=_render_status_html(_final_state, log_text, _final_elapsed if _final_state == 'running' else '', task_list))
        # 最终 yield:按钮切回 RESTING,media_html 用 last_media(若有),
        # 保留刚生成的图/视频/音频,不要被 _media_to_html(None, ...) 覆盖成占位。
        yield (
            log_text,
            _media_to_html(last_media, output_kind),
            gr.update(value="", visible=False),
            gr.update(visible=False),
            gr.update(value="", visible=False),
            _RUN_BTN_RESTING,
            _final_status_bar,
        )


    # P2: status_bar 作为第 7 个 output —— 跟 run_btn 一起 morph, 实时反映运行状态
    run_click_outputs = [status_box, output_box, error_box, re_run_btn, open_dir_msg, run_btn, status_bar]
    run_btn.click(fn=_run_and_format, inputs=inputs, outputs=run_click_outputs)
    re_run_btn.click(fn=_run_and_format, inputs=inputs, outputs=run_click_outputs)

    def _build_loader(loader_fn):
        """把 "返回 inputs 列表" 的 loader 包成 "返回 inputs + 缩略图"。
        缩略图需要收到对应的文件路径才能显示, 文本/数字类的非 file spec 不传缩略图。
        """
        def _run():
            vals = loader_fn()
            extras = [vals[i] if 0 <= i < len(vals) else None for i in _preview_value_at]
            return list(vals) + extras
        return _run

    ex_outputs = inputs + preview_components
    if ex_btn is not None:
        # "load example" = explicit reset to example. Switching to another workflow
        # and back should keep the example state, not be overwritten by auto-load.
        def _on_ex_btn_click():
            _AUTO_LOADED.add(preset_name)
            return _build_loader(lambda: example_to_form_values(preset_name))()
        ex_btn.click(fn=_on_ex_btn_click, outputs=ex_outputs)

    def _fill_last_run():
        # mark as loaded so switching to another workflow and back
        # does not lose the last-run parameter values
        _AUTO_LOADED.add(preset_name)
        return _build_loader(lambda: _load_last_run(preset_name, len(inputs)))()
    last_btn.click(fn=_fill_last_run, outputs=ex_outputs)

    def _open_dir_and_show():
        msg = _open_output_dir_action()
        return gr.update(value=msg, visible=True)
    open_dir_btn.click(fn=_open_dir_and_show, outputs=[open_dir_msg])

    return inputs


# 深色主题 CSS（按建议文档配色：背景深灰、卡片分层、统一圆角间距）
# Gradio 6: css/theme 传给 launch()，故作为模块常量供 main() 使用
# =====================================================================
# CSS / Theme —— 单一来源是 app/static/tokens.css,运行时主题切换靠 _apply_theme。
# 升级 Gradio 时所有自定义类名(.btn-run-primary / .card-core / ...) 都用
# elem_classes 显式挂载,与原生 .gr-button / .gradio-container 解耦。
# =====================================================================

# [迁移 2026-07-21] 主题/CSS/head 相关的 7 个函数 + 6 个模块常量已抽到
# app.services.theme. 这里 import 回来, 保持 scail2_app.py 公开 API 不变.
from app.services.theme import (
    _TOKENS_CACHE,
    _THEMES_CACHE,
    _DEFAULT_THEME_ID,
    _THEMES_PATH,
    _TOKENS_PATH,
    _PAGE_BG_COLOR,
    _load_tokens_css,
    _list_themes,
    _load_saved_theme,
    _save_theme,
    _apply_theme,
    _build_launch_css,
    _strip_style_tag,
    _get_theme_desc,
    _build_launch_head,
)


CSS = _build_launch_css()
HEAD = _build_launch_head()


THEME = gr.themes.Soft(primary_hue="orange", neutral_hue="slate").set(
    body_background_fill="#111315",
    block_background_fill="#1b1d22",
    block_border_color="#2a2d33",
    block_radius="12px",
)


def build_ui():
    """组装完整 UI。

    设计要点:
    - 左侧: 搜索 + 类别 radio + ComfyUI 连接状态指示灯。Radio 选项的 label 包含分类 emoji。
    - 右侧: 每个 preset 一次性预渲染到独立的 gr.Group 内,通过 visibility 切换可见性。
      与原来的 @gr.render 不同 —— @gr.render 会重新创建组件,这次切 preset 时组件不被销毁,
      表单状态由 Gradio 自动保留。
    - Tab 命名 "运行" 而不是 "开始使用",与"运行器"产品定位对齐。
    """
    workflows = config.list_workflows()
    preset_names = [w["name"] for w in workflows]
    default_wf = workflows[0]["name"]

    # Radio label: use module-level _wf_label (review P0-2: English category suffix removed)
    full_choices = [(_wf_label(w), w["name"]) for w in workflows]

    # analytics_enabled=False —— 切断前端向 huggingface.co 发 telemetry 的外网请求。
    # footer_links=[] —— 去掉底部"API"/"gradio"等外链(点击会跳外站)。
    # 本 WebUI 必须完全本地自包含,任何外网依赖都会在离线/弱网下导致 SPA 卡在加载界面。
    with gr.Blocks(title="ComfyUI Web Workflow", analytics_enabled=False) as demo:
        # 色彩注入器 —— 主题切换时把 <style>:root{}</style> 写到 value,
        # DOM 里的 :root 变量即刻刷新,所有消费 --theme-* 的组件毫秒级变色。
        # visible 必须 True:Gradio 6 对 visible=False 的组件不渲染 DOM,回调写入的
        # 新 <style> 不会出现在页面上 → 主题切换没效果。<style> 标签本身在浏览器里
        # 是 display:none(CSS 标准),所以 visible=True 也不会占视觉空间。
        # 必须在 Blocks 上下文内创建:否则它会被分配组件 ID 但不进 components 列表,
        # 导致 layout 树引用不存在的组件 -> Svelte 前端渲染卡死在"加载中"。
        theme_injector = gr.HTML(value=_apply_theme(_load_saved_theme()), visible=True, elem_id="theme-injector")

        # review P2-5: page has no h1 / h2 (HEADERS: []). Add app title above Tabs so the
        # first viewport has a visible brand instead of jumping straight into form.
        gr.Markdown("# 🎬 ComfyUI 工作流运行器")

        with gr.Tabs() as main_tabs:
            with gr.Tab("运行"):
                with gr.Row():
                    # ============ LEFT COLUMN (导航) ============
                    # scale=0 + min_width=200 让导航固定 200px,其余宽度全部给主工作区。
                    # 原 scale=1 把主区宽度乘 1/5 = 224px,导致主区内容被压扁 → review P0。
                    with gr.Column(scale=0, min_width=200):
                        # P3 左侧导航拆组 —— review 副标题 1/2
                        # 原结构把『导航』(搜索 + 工作流列表) 和『系统状态』(ComfyUI 连通 + 刷新)
                        # 混在一列,用户难以分辨『这是入口』还是『这是状态栏』。
                        # 拆成两个独立 Group + 中间 divider → review P3 副标题 1/2。

                        # ===== 导航 Group =====
                        with gr.Group(elem_classes=["nav-group"]):
                            gr.Markdown("**导航**")
                            wf_search = gr.Textbox(
                                label="🔍 搜索",
                                placeholder="按名称筛选...",
                                show_label=False,
                                container=False,
                                max_lines=1,
                            )
                            wf_radio = gr.Radio(
                                choices=full_choices,
                                value=default_wf,
                                label="选择工作流",
                                show_label=False,
                                container=False,
                                elem_id="wf-nav",
                                elem_classes=["custom-radio"],
                            )
                            # 搜索 → 过滤 choices
                            def _filter_choices(query, current):
                                q = (query or "").strip().lower()
                                if not q:
                                    new_choices = full_choices
                                else:
                                    new_choices = [
                                        (label, val) for (label, val) in full_choices
                                        if q in label.lower() or q in val.lower()
                                    ]
                                if not new_choices:
                                    new_value = None
                                else:
                                    new_value = current if any(v == current for _, v in new_choices) else new_choices[0][1]
                                return gr.update(choices=new_choices, value=new_value)
                            wf_search.change(
                                fn=_filter_choices,
                                inputs=[wf_search, wf_radio],
                                outputs=[wf_radio],
                            )

                        # ----- divider 视觉分隔 -----
                        gr.HTML('<div class="nav-divider"></div>')

                        # ===== 系统 Group =====
                        with gr.Group(elem_classes=["nav-group", "nav-group-system"]):
                            gr.Markdown("**系统**")
                            comfy_status = gr.Markdown(_comfy_status_text())
                            refresh_status_btn = gr.Button("🔄 刷新状态", size="sm")
                            refresh_status_btn.click(
                                fn=_comfy_status_text,
                                outputs=[comfy_status],
                            )
                            open_output_btn = gr.Button(
                                '📁 打开输出文件夹', size='sm',
                            )
                            open_output_btn.click(
                                fn=_open_comfy_output_dir,
                                outputs=[comfy_status],
                            )


                    # ============ RIGHT COLUMN ============
                    with gr.Column(scale=4, elem_classes=["preset-panels-host"]):
                        # 关键改动:每个 preset 预渲染到自己 Group 里,通过 visibility 切换。
                        # 这样切换 workflow 时组件不被销毁,表单状态自动保留。
                        # 注意: 这个 column 的 CSS gap 必须为 0 (见 tokens.css .preset-panels-host),
                        # 因为 Gradio 6 的 visible=False 只把 panel height 设 0 而不移出 flex 流,
                        # flex gap:16px 会在隐藏 panel 之间累加 → 越往后空白越多。
                        preset_panel_groups: dict[str, object] = {}
                        preset_inputs_map: dict[str, list] = {}
                        for wf in workflows:
                            with gr.Group(
                                visible=(wf["name"] == default_wf),
                                elem_id=f"panel-{wf['name']}",
                                elem_classes=["preset-panel"],
                            ) as g:
                                preset_panel_groups[wf["name"]] = g
                                preset_inputs_map[wf["name"]] = _render_workflow_form(wf["name"])

                        # 切换 visibility 的 handler
                        def _switch_panel(name):
                            return [
                                gr.update(visible=(n == name))
                                for n in preset_panel_groups
                            ]
                        wf_radio.change(
                            fn=_switch_panel,
                            inputs=[wf_radio],
                            outputs=list(preset_panel_groups.values()),
                        )

                        # Auto-load example:切换 preset 时自动把 example 填进表单。
                        # 让 "📥 加载示例素材" 按钮的语义变成 "重置回 example",而不是 "首次加载"。
                        # 用户进工作台即可看到完整可跑的示例参数,无需先点按钮。
                        all_inputs_flat = [inp for _ins in preset_inputs_map.values() for inp in _ins]

                        # 跨 tab 状态：记住全部表单输入 + wf_radio + tabs，供历史 tab 的“加载到运行”按钮使用。
                        global _ALL_INPUTS_FLAT, _WF_RADIO_REF, _TABS_REF
                        _ALL_INPUTS_FLAT = all_inputs_flat
                        _WF_RADIO_REF = wf_radio
                        _TABS_REF = main_tabs

                        def _auto_load_example(name):
                            # 委托给模块级函数 (review 2026-07-11 P-state-preserve),
                            # 契约见 _resolve_auto_load_updates 的 docstring.
                            return _resolve_auto_load_updates(preset_inputs_map, name)

                        wf_radio.change(
                            fn=_auto_load_example,
                            inputs=[wf_radio],
                            outputs=all_inputs_flat,
                        )

                        # 首次进入页面时,加载 default preset 的 example
                        demo.load(
                            fn=lambda: _auto_load_example(default_wf),
                            outputs=all_inputs_flat,
                        )

                        # review 2026-07-17 排版审计: 加 elem_classes 给页脚 margin-top。
                        # .preset-panels-host gap:0 (锁定, Gradio 6 visible=False bug workaround)
                        # 让这个页脚贴着 preset panel 底部无呼吸; 这里用 CSS 类加 margin-top,
                        # 不破坏 host gap:0 契约。
                        gr.Markdown(
                            f"<small style='color:var(--text-faint)'>"
                            f"限制: 参考图 ≤{config.MAX_IMAGE_MB}MB / 驱动视频 ≤{config.MAX_VIDEO_MB}MB / "
                            f"提示词 ≤{config.MAX_PROMPT_CHARS}字符 · 超时 {config.DEFAULT_TIMEOUT_SEC // 60} 分钟"
                            f"</small>",
                            elem_classes=["footer-notice"],
                        )

            with gr.Tab("系统设置"):
                _build_settings_tab(theme_injector)

    return demo



def main():
    print("=" * 60)
    print("SCAIL-2 Web UI — preflight check")
    print("=" * 60)
    print(_preflight())
    print("=" * 60)
    demo = build_ui()
    # Gradio 6.x: generator function (yield) must explicitly queue() to dispatch
    demo.queue()
    # Gradio 6: theme/css 从 launch() 注入（不再放 Blocks 构造函数）
    # allowed_paths: 项目内的示例图等静态资源走 /gradio_api/file= 路由时,
    # Gradio 6 默认只允许 cache_dir,需要显式把 app/static/examples 加进去。
    demo.launch(
        server_name=config.GRADIO_HOST,
        server_port=config.GRADIO_PORT,
        show_error=True,
        theme=THEME,
        css=CSS,
        head=HEAD,
        footer_links=[],
        enable_monitoring=False,
        allowed_paths=[config.REPO_ROOT / "app" / "static" / "examples"],
    )


if __name__ == "__main__":
    main()