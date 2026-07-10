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
# 这些组件在 build_ui 里创建，build_ui 赋值到这三个模块变量，_build_history_tab 里读取。
_ALL_INPUTS_FLAT: list = []
_WF_RADIO_REF = None  # type: ignore[assignment]
_TABS_REF = None  # type: ignore[assignment]
_SKIP_AUTO_LOAD: set = set()  # 后续要被快速取消，临时标记“下一次 wf_radio.change 跳过自动填表单”


def _iter_preset_names():
    """顺序返回所有 preset name（与 build_ui 里 preset_inputs_map 的顺序一致）。
    build_ui 里是走 config.list_workflows()（按 order 排序），这里复用同一个函数。"""
    return [w["name"] for w in config.list_workflows()]



# --- 预估段数 / 帧数探测 ---

def get_video_frames(path):
    """用 ffprobe 读驱动视频总帧数。失败返 None。"""
    if not path:
        return None
    try:
        r = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-count_frames", "-show_entries", "stream=nb_read_frames",
            "-of", "csv=p=0", str(path),
        ], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


def estimated_segments(frames, per_seg, pre_drop, max_segments=0):
    """估算段数 = 1 + ceil(max(0, video_frames - per_seg) / max(1, per_seg - pre_drop))。"""
    if frames is None or frames <= 0:
        return None
    per_seg = max(1, int(per_seg))
    pre_drop = max(0, int(pre_drop))
    net = max(1, per_seg - pre_drop)
    auto = max(1, 1 + math.ceil(max(0, frames - per_seg) / net))
    if max_segments and max_segments > 0:
        return min(auto, int(max_segments))
    return auto


# --- 输入校验 ---

def _file_extension(p):
    if not p:
        return ""
    return Path(p).suffix.lower()


def _file_size_mb(p):
    if not p:
        return 0.0
    try:
        return Path(p).stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0


def validate_inputs(ref_path, drive_path, preset_cfg):
    if not ref_path:
        return "参考图未上传"
    ext = _file_extension(ref_path)
    if ext not in config.ALLOWED_IMAGE_EXT:
        return f"参考图扩展名不支持: {ext}（允许: {sorted(config.ALLOWED_IMAGE_EXT)}）"
    if _file_size_mb(ref_path) > config.MAX_IMAGE_MB:
        return f"参考图过大: {_file_size_mb(ref_path):.1f}MB（上限 {config.MAX_IMAGE_MB}MB）"
    if not drive_path:
        return "驱动视频未上传"
    ext = _file_extension(drive_path)
    if ext not in config.ALLOWED_VIDEO_EXT:
        return f"驱动视频扩展名不支持: {ext}（允许: {sorted(config.ALLOWED_VIDEO_EXT)}）"
    if _file_size_mb(drive_path) > config.MAX_VIDEO_MB:
        return f"驱动视频过大: {_file_size_mb(drive_path):.1f}MB（上限 {config.MAX_VIDEO_MB}MB）"
    return None


# --- 表单 schema → Gradio components ---

import re as _re

_SIZE_PAT = _re.compile(r"(\d+)\s*[x×]\s*(\d+)")


def parse_sizes(value):
    """把尺寸输入解析成 (w, h) 或 list[(w,h)...]。

    严格 fullmatch(拒绝包含多余文本或逗号分隔的字符串):
    - "1024x1024" → (1024, 1024)
    - ["1024x1024", "1280x720"] → [(1024,1024), (1280,720)]
    无法解析返回 None(单值)或跳过(list)。

    "1024x1024, 800x600" 这种多 size 字符串以前会"取第一个"返回,UI 里走不到；
    收紧为 strict 解析后,多 size 走 list 形式(CheckboxGroup 直接给 list)。
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            if v is None:
                continue
            m = _SIZE_PAT.fullmatch(str(v).strip())
            if m:
                out.append((int(m.group(1)), int(m.group(2))))
        return out
    m = _SIZE_PAT.fullmatch(str(value).strip())
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return None


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
            label=label, value=spec.get("default", ""), max_lines=4,
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
        )
    if typ == "bool":
        return gr.Checkbox(
            value=bool(spec.get("default", False)),
            label=label,
            info=spec.get("help"),
        )
    if typ == "int":
        return gr.Slider(
            minimum=spec["min"], maximum=spec["max"],
            value=spec["default"], step=spec.get("step", 1), label=label,
            info=spec.get("help"),
        )
    raise ValueError(f"unknown input type: {typ}")


def _build_form(preset_cfg):
    return [_build_input_component(spec) for spec in preset_cfg["user_facing_inputs"]]


def example_to_form_values(preset_name):
    """把 preset 的 example 字典映射回表单值列表（按 user_facing_inputs 顺序）。

    给 UI 的"加载示例"按钮用：点击后一次性填好整个表单。
    映射规则（按 spec 的 node_id + type）：
    - file:image → example["reference_image"]（解析成绝对路径，见 _resolve_example_file）
    - file:video → example["drive_video"]
    - node 362 (抠参考图提示词) → example["ref_prompt"]
    - node 348 (抠驱动视频提示词) → example["drive_prompt"]
    - node 360 (主提示词) → example["main_prompt"]
    - node 479 (段数) → example["segments"]
    - prompt_pool → example["prompt"]
    - 其它 → spec 的 default

    重要：文件槽位必须返回**绝对路径**。gr.File(type='filepath').postprocess 会对
    纯文件名调 Path(name).stat()，文件在 COMFY_INPUT_DIR 不在 CWD → FileNotFoundError
    → 整个表单更新静默失败。所以这里拼成 COMFY_INPUT_DIR 下的绝对路径。
    运行时 _resolve_upload_name 已能识别 COMFY_INPUT_DIR 的文件跳过上传。
    """
    cfg = config.preset_config(preset_name)
    ex = cfg.get("example", {})
    values = []
    for spec in cfg["user_facing_inputs"]:
        nid = str(spec.get("node_id", ""))
        typ = spec.get("type")
        if typ == "file:image":
            values.append(_resolve_example_file(ex.get("reference_image")))
        elif typ == "file:video":
            values.append(_resolve_example_file(ex.get("drive_video")))
        elif typ == "prompt_pool":
            values.append(ex.get("prompt", spec.get("default", "")))
        elif typ == "image_sizes":
            values.append(list(ex.get("sizes") or spec.get("default") or []))
        elif nid == "362":
            values.append(ex.get("ref_prompt", spec.get("default", "")))
        elif nid == "348":
            values.append(ex.get("drive_prompt", spec.get("default", "")))
        elif nid == "360":
            values.append(ex.get("main_prompt", spec.get("default", "")))
        elif nid == "479":
            values.append(ex.get("segments", spec.get("default", 0)))
        elif spec.get("field") == "seed":
            values.append(ex.get("seed", spec.get("default", 0)))
        else:
            values.append(spec.get("default"))
    return values


def _manifest_to_form_values(preset_name, manifest):
    """把 manifest 数据映射回 user_facing_inputs 顺序的表单值。

    与 example_to_form_values 对称，但数据来源是运行历史而不是 preset.example。
    - 复用 _resolve_example_file 解析文件字段（example 走 staged path，manifest 走原始 basename）
    - seed / sizes / ref_prompt / drive_prompt / main_prompt 都是可选的，老 manifest 里没有就回退 spec.default
    - 调用方需要保证 manifest["preset"] == preset_name（点击 rerun 时已校验）
    """
    if not manifest:
        cfg = config.preset_config(preset_name)
        return [spec.get("default") for spec in cfg["user_facing_inputs"]]
    cfg = config.preset_config(preset_name)
    values = []
    for spec in cfg["user_facing_inputs"]:
        nid = str(spec.get("node_id", ""))
        typ = spec.get("type")
        field = spec.get("field", "")
        if typ == "file:image":
            values.append(_resolve_example_file(manifest.get("reference_image", "")))
        elif typ == "file:video":
            values.append(_resolve_example_file(manifest.get("drive_video", "")))
        elif typ == "prompt_pool":
            values.append(manifest.get("prompt_text", spec.get("default", "")))
        elif typ == "image_sizes":
            sizes = manifest.get("sizes")
            values.append(list(sizes or spec.get("default") or []))
        elif field == "seed":
            seed = manifest.get("seed")
            values.append(seed if seed is not None else spec.get("default", 0))
        elif nid == "362":
            values.append(manifest.get("ref_prompt", spec.get("default", "")))
        elif nid == "348":
            values.append(manifest.get("drive_prompt", spec.get("default", "")))
        elif nid == "360":
            # 老 manifest 只存了 prompt_text（折叠三个 prompt），回退到它
            values.append(manifest.get("main_prompt", manifest.get("prompt_text", spec.get("default", ""))))
        elif nid == "367":
            values.append(manifest.get("frames_per_segment", spec.get("default", 81)))
        elif nid == "464":
            values.append(manifest.get("pre_drop_frames", spec.get("default", 5)))
        elif nid == "479":
            values.append(manifest.get("max_segments", spec.get("default", 0)))
        else:
            values.append(spec.get("default"))
    return values


def _resolve_example_file(filename):
    """把 example 里的文件名解析成 gr.File 能接受的路径。

    Gradio 6 安全限制：gr.File 不接受"应用外部"的文件路径（不在 CWD 也不在
    gradio cache dir），会报 "Cannot move ... to the gradio cache dir"。
    所以这里把 ComfyUI input 目录的文件**复制到项目内的 .examples_cache/**
    （在 CWD 下），返回复制后的路径。运行时 _resolve_upload_name 会正常上传它。

    - 文件在 COMFY_INPUT_DIR → 复制到 .examples_cache/ 返回该路径
    - 文件不存在 → 返回 None（不崩，让用户手动上传）
    - filename 为空 → None
    """
    if not filename:
        return None
    # 找源文件：先按绝对路径，再拼 COMFY_INPUT_DIR
    src = Path(filename)
    if not src.is_absolute():
        src = config.COMFY_INPUT_DIR / filename
    if not src.exists():
        # 也可能在 CWD 下（已经是 staged 的）
        src = Path(filename)
        if not src.exists():
            return None
    # 复制到 CWD 下的 .examples_cache/（Gradio 接受 CWD 内的文件）
    cache_dir = config.REPO_ROOT / ".examples_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dst = cache_dir / src.name
    if not dst.exists():
        import shutil
        shutil.copy2(src, dst)
    return str(dst)


# --- 主流程 ---

def _is_comfy_input_file(filename):
    """判断文件名是否已存在于 ComfyUI input 目录（example 加载场景，可跳过上传）。"""
    if not filename:
        return False
    # 纯文件名（无路径分隔符）= 用户直接填的 ComfyUI 端文件名
    if "/" in filename or "\\" in filename:
        return False
    return (config.COMFY_INPUT_DIR / filename).exists()



def _resolve_upload_name(file_value, kind="image"):
    """解析上传后的文件名。

    - 若 file_value 是纯文件名且已在 ComfyUI input 目录（example 场景）→ 直接返回，跳过上传
    - 否则走 scail2_client.upload 上传，返回上传后的 name
    """
    if not file_value:
        return None
    if _is_comfy_input_file(file_value):
        return file_value
    result = scail2_client.upload(file_value, kind=kind)
    return result["name"]


def _extract_status_kind(status_msg):
    if status_msg.startswith("✅"):
        return "success", None
    if status_msg.startswith("❌"):
        return "failure", status_msg[1:].strip()
    if status_msg.startswith("⏰"):
        return "timeout", status_msg[1:].strip()
    return None, None


def run_workflow(preset_name, *component_values):
    """运行指定 preset 的 workflow。preset_name 决定走哪个模板。

    component_values 顺序对应 preset 的 user_facing_inputs（由 UI 按序传入）。
    生成器 yield (status_msg, output_url) 给 Gradio 流式更新。
    同时用 gr.Progress 推进度条（0~1 + 描述）。
    """
    progress = gr.Progress()
    _log.info(f"[run_workflow] ENTRY preset={preset_name}, {len(component_values)} values")
    try:
        progress(0.02, desc="准备中...")
        yield "[READY] preparing...", None
    except Exception as e:
        _log.error("[run_workflow] early yield exception: " + repr(e), exc_info=True)
        yield "[ERROR] early yield: " + repr(e), None
        raise
    preset_cfg = config.preset_config(preset_name)
    _log.debug(f"start preset={preset_name}, {len(component_values)} component values")

    inputs_spec = preset_cfg["user_facing_inputs"]
    text_by_node: dict[str, str] = {}
    file_by_type: dict[str, str] = {}
    int_by_node: dict[str, int] = {}
    for spec, value in zip(inputs_spec, component_values):
        nid = str(spec["node_id"])
        typ = spec["type"]
        if typ == "text":
            text_by_node[nid] = value or ""
        elif typ == "file:image":
            file_by_type["image"] = value
        elif typ == "file:video":
            file_by_type["video"] = value
        elif typ == "int":
            int_by_node[nid] = int(value) if value is not None else spec.get("default", 1)
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

    progress(0.10, desc="上传参考图...")
    yield "⏳ [1/5] uploading reference image...", None
    try:
        ref_name = _resolve_upload_name(ref_path, kind="image")
    except (ComfyUIError, FileNotFoundError) as e:
        gr.Error(str(e))
        progress(0, desc=f"❌ 上传失败: {e}")
        yield f"❌ upload ref: {e}", None
        return

    progress(0.20, desc="上传驱动视频...")
    yield "⏳ [2/5] uploading drive video...", None
    try:
        drive_name = _resolve_upload_name(drive_path, kind="file")
    except (ComfyUIError, FileNotFoundError) as e:
        gr.Error(str(e))
        progress(0, desc=f"❌ 上传失败: {e}")
        yield f"❌ upload drive: {e}", None
        return

    progress(0.30, desc="组装 workflow...")
    yield "⏳ [3/5] loading + patching workflow...", None
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
                replacements[nid] = {field: ref_name}
            elif typ == "file:video":
                replacements[nid] = {field: drive_name}
            elif typ in ("text", "prompt_pool"):
                raw = text_by_node.get(nid, "")
                final = (raw or "").strip() or (spec.get("default") or config.DEFAULT_PROMPT_TEXT)
                replacements[nid] = {field: final}
            elif typ == "int":
                default = spec.get("default", 1)
                val = int_by_node.get(nid, default)
                # max_segments=0 (默认) 不 patch，保留 workflow 原始的 [495, 1] 引用
                if nid == "479" and val == 0:
                    pass
                else:
                    replacements[nid] = {field: val}
        patched = scail2_client.patch_workflow(
            wf, replacements, preset_config=preset_cfg, validate_after=True,
        )
    except (WorkflowValidationError, FileNotFoundError) as e:
        gr.Error(str(e))
        yield f"❌ patch: {e}", None
        return

    progress(0.40, desc="入队 ComfyUI...")
    yield "⏳ [4/5] queuing prompt to ComfyUI...", None
    try:
        prompt_id = scail2_client.queue_prompt(patched, client_id="gradio-ui")
    except (ComfyUIError, ProtocolError_) as e:
        gr.Error(str(e))
        progress(0, desc=f"❌ 入队失败: {e}")
        yield f"❌ queue: {e}", None
        return
    prompt_id_final = prompt_id
    yield f"⏳ [4/5] queued: {prompt_id[:8]}…", None

    video_url = None
    progress(0.45, desc="等待 ComfyUI 执行...")
    yield "⏳ [5/5] waiting for ComfyUI execution...", None
    _wait_p = 0.45
    for status_msg in scail2_client.wait_for_completion(prompt_id):
        # 进度按轮询渐进推进（0.45 → 0.92），留 0.08 给最终完成
        _wait_p = min(0.92, _wait_p + 0.02)
        progress(_wait_p, desc=status_msg.lstrip("⏳✅❌⏰ ").strip()[:40] or "执行中...")
        if status_msg.startswith("✅"):
            try:
                hist = scail2_client.get_history(prompt_id)
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

    # 最终进度：成功 1.0，失败/超时也归零并标注
    if final_status == "success":
        progress(1.0, desc="完成")
    else:
        progress(0, desc=f"❌ {final_status}")

    finished_at = datetime.now(timezone.utc)
    if prompt_id_final:
        try:
            fps = int_by_node.get("367", 81)
            pre = int_by_node.get("464", 5)
            mx = int_by_node.get("479", 0)
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
    yield "[READY] preparing image gen...", None

    preset_cfg = config.preset_config(preset_name)
    inputs_spec = preset_cfg["user_facing_inputs"]

    # 把 component_values 映射到 spec
    prompt_text = ""
    sizes_raw = None
    seed_val = 0
    prompt_node_id = None
    sizes_node_id = None
    seed_node_id = None
    for spec, value in zip(inputs_spec, component_values):
        typ = spec["type"]
        nid = str(spec["node_id"])
        if typ == "prompt_pool":
            prompt_text = value or ""
            prompt_node_id = nid
        elif typ == "image_sizes":
            sizes_raw = value
            sizes_node_id = nid
        elif typ == "int":
            seed_val = int(value) if value is not None else spec.get("default", 0)
            seed_node_id = nid

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

    yield f"⏳ 准备生成 {len(sizes)} 张图...", None

    progress(0.05, desc=f"准备生成 {len(sizes)} 张图...")
    yield f"⏳ 准备生成 {len(sizes)} 张图...", None

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
        progress(seg_start + 0.02, desc=f"[{idx}/{len(sizes)}] {w}x{h} 生成中...")
        yield f"⏳ [{idx}/{len(sizes)}] {w}x{h} seed={actual_seed}...", None
        try:
            patched = scail2_client.patch_workflow(
                wf_base, replacements, preset_config=preset_cfg, validate_after=False,
            )
            prompt_id = scail2_client.queue_prompt(patched, client_id="gradio-ui-image")
            prompt_ids.append(prompt_id)
        except (ComfyUIError, ProtocolError_, WorkflowValidationError, FileNotFoundError) as e:
            gr.Error(str(e))
            final_status = "failure"
            final_error = str(e)
            yield f"❌ [{idx}/{len(sizes)}] queue failed: {e}", list(gallery_urls)
            continue

        # 轮询这一个尺寸
        _seg_p = seg_start
        for status_msg in scail2_client.wait_for_completion(prompt_id):
            kind, err = _extract_status_kind(status_msg)
            if kind == "failure":
                final_status = "failure"
                if err:
                    final_error = err
            elif kind == "timeout":
                final_status = "timeout"
            _seg_p = min(seg_end - 0.01, _seg_p + 0.02)
            progress(_seg_p, desc=status_msg.lstrip("⏳✅❌⏰ ").strip()[:40])
            yield f"[{idx}/{len(sizes)}] {status_msg}", list(gallery_urls)
            if status_msg.startswith(("✅", "❌", "⏰")):
                break

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


def _run_row(run: dict[str, Any]) -> list[str]:
    """把一条 manifest 拍平成 Dataframe 一行 (6 列精简版)。

    status 列返回 HTML badge 字符串,Dataframe 会按字符串渲染;其余列保持纯文本。
    详细字段(参考图 / 驱动视频 / cache / 段数估 / 参数组)放到详情卡片。
    """
    status = run.get("status", "unknown")
    badge = (
        f"<span class='status-badge status-badge-{status}'>"
        f"{_status_label(status)}</span>"
    )
    prompt = run.get("prompt_text", "") or ""
    if len(prompt) > 60:
        prompt = prompt[:60] + "…"
    return [
        run.get("created_at", "?")[:19].replace("T", " "),
        badge,
        run.get("preset", "?"),
        f"{run.get('duration_sec', '?')}s",
        prompt,
        run.get("prompt_id", "?")[:8],
    ]


def _status_label(status: str) -> str:
    """把内部状态值翻译成中文短标签(badge 显示用)。"""
    return {
        "success": "✓ 成功",
        "failure": "✗ 失败",
        "timeout": "⚠ 超时",
        "running": "● 运行中",
    }.get(status, status or "未知")


def _make_detail_from_run(run: dict[str, Any] | None) -> tuple[str, str, str, str]:
    """从单条 manifest 构造 detail (summary_html, media_html, json_str, prompt_md)。

    summary_html 是一段结构化 HTML(卡片化展示关键字段),media_html 是输出预览,
    json_str 是原始 manifest JSON(给隐藏 manifest 组件 + rerun 用),
    prompt_md 是带代码块包裹的提示词全文(给 "提示词全文" accordion 用)。
    """
    empty = (
        "<div class='detail-empty'>选中一条记录查看详情</div>",
        "<div class='detail-empty'>—</div>",
        "",
        "",
    )
    if not run:
        return empty

    status = run.get("status", "unknown")
    badge_html = f"<span class='status-badge status-badge-{status}'>{_status_label(status)}</span>"

    media_html = "<div class='detail-empty'>无输出文件</div>"
    if run.get("output"):
        view_url = history.make_view_url(
            run["output"]["filename"],
            run["output"].get("subfolder", ""),
            run["output"].get("type", "output"),
        )
        is_image = run.get("preset") == "zimage" or                    str(run["output"].get("filename", "")).endswith((".png", ".jpg", ".jpeg", ".webp"))
        media_html = _media_to_html(view_url, is_image)

    # 关键字段卡片(表格被简化后,详情须补上这些)
    fields = []
    fields.append(("Preset", run.get("preset", "?")))
    fields.append(("Prompt ID", f"<code>{run.get('prompt_id', '?')}</code>"))
    fields.append(("开始", _fmt_time(run.get("created_at"))))
    fields.append(("结束", _fmt_time(run.get("finished_at"))))
    fields.append(("耗时", f"{run.get('duration_sec', '?')}s"))
    fields.append(("Cache hit", "是" if run.get("cache_hit") else "否"))

    preset = run.get("preset", "")
    if preset == "zimage":
        sizes = run.get("sizes") or []
        if sizes:
            fields.append(("尺寸", " / ".join(str(s) for s in sizes)))
        seed = run.get("seed")
        if seed is not None:
            fields.append(("Seed", str(seed)))
    else:
        ref = run.get("reference_image") or "—"
        drive = run.get("drive_video") or "—"
        fields.append(("参考图", _truncate(ref, 40)))
        fields.append(("驱动视频", _truncate(drive, 40)))
        if run.get("frames_per_segment") is not None:
            fields.append(("每段帧数", str(run["frames_per_segment"])))
        if run.get("pre_drop_frames") is not None:
            fields.append(("段间帧数", str(run["pre_drop_frames"])))
        if run.get("video_frames") is not None:
            fields.append(("驱动总帧数", str(run["video_frames"])))
        if run.get("estimated_segments") is not None:
            fields.append(("预估段数", str(run["estimated_segments"])))

    if run.get("error"):
        fields.append(("错误", f"<span class='detail-error'>{_escape(run['error'])}</span>"))
    if run.get("output"):
        dl_url = history.make_view_url(
            run["output"]["filename"],
            run["output"].get("subfolder", ""),
            run["output"].get("type", "output"),
        )
        fields.append(("输出", f"<a href='{dl_url}' target='_blank'>{run['output']['filename']}</a>"))

    summary_html = _render_summary_html(badge_html, fields, run.get("prompt_text", "") or "")
    json_str = json.dumps(run, ensure_ascii=False, indent=2)
    prompt_md = _wrap_prompt_markdown(run.get("prompt_text", "") or "")
    return summary_html, media_html, json_str, prompt_md


def _wrap_prompt_markdown(text):
    """把提示词包成 markdown 代码块(供 accordion 用)。空文本返空串。"""
    if not text:
        return ""
    return f"```\n{text}\n```"


def _fmt_time(iso):
    """精简 ISO 时间到分钟。空/无效返 "—"。"""
    if not iso or not isinstance(iso, str):
        return "—"
    return iso[:19].replace("T", " ") or "—"


def _truncate(text, max_len):
    if not text:
        return "—"
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _escape(text):
    """轻量 HTML 转义(用于用户输入文本场景,避免页面报错)。"""
    if text is None:
        return ""
    s = str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_summary_html(badge_html, fields, prompt):
    """拼装详情卡片:顶部 badge + 关键字段 + prompt 预览。"""
    field_rows = "".join(
        f"<div class='detail-field'><span class='detail-label'>{_escape(k)}</span>"
        f"<span class='detail-value'>{v}</span></div>"
        for k, v in fields
    )
    prompt_block = ""
    if prompt:
        prompt_block = (
            "<div class='detail-prompt'>"
            "<div class='detail-label'>提示词</div>"
            f"<div class='detail-prompt-body'>{_escape(prompt)}</div>"
            "</div>"
        )
    return (
        "<div class='detail-card'>"
        f"<div class='detail-header'>{badge_html}</div>"
        f"<div class='detail-fields'>{field_rows}</div>"
        f"{prompt_block}"
        "</div>"
    )


def _refresh_history_filtered(preset: str, status: str) -> tuple[list[list[str]], str, str, str, str, str]:
    """按 preset + status 过滤后,刷新 dataframe + 详情。

    返回: (rows, summary_html, media_html, json_str, prompt_md, count_label)
    count_label 是屏幕只读的记录数提示,例如 "共 12 条"。
    """
    p = preset if preset and preset != "全部" else None
    s_arg = status if status and status != "全部" else None
    runs = history.list_runs(preset=p, status=s_arg)
    rows = [_run_row(r) for r in runs]
    summary_html, media_html, json_str, prompt_md = _make_detail_from_run(runs[0] if runs else None)
    count_label = f"共 {len(runs)} 条"
    return rows, summary_html, media_html, json_str, prompt_md, count_label


def _build_history_tab():
    """历史记录 tab:左 Dataframe + 右详情卡片的两栏布局。

    表格列从 10 列精简到 6 列(时间 / 状态 badge / preset / 耗时 / prompt / id),
    详细字段(参考图 / 驱动视频 / cache / 段数估 / 参数组 / 输出文件)挪到右侧详情
    卡片。详情默认展示 badge + 关键字段 + 提示词摘要,提示词全文与原始 manifest
    折叠收起;rerun 按钮始终可见,直接把 manifest 喂回运行表单。
    """
    gr.Markdown("## 历史记录")
    gr.Markdown(
        f"manifest 目录 `{config.RUNS_DIR}`。切换过滤条件或点「🔃 刷新」重新读取。"
    )

    workflows = config.list_workflows()
    preset_options = [("全部", "全部")] + [(w["display_name"], w["name"]) for w in workflows]
    status_options = [
        ("全部", "全部"),
        ("成功", "success"),
        ("失败", "failure"),
        ("超时", "timeout"),
    ]

    # 筛选条:Preset 下拉 + 状态 pills + 结果数 + 刷新,挤在一行
    with gr.Row(elem_classes=["history-filter-bar"]):
        preset_filter = gr.Dropdown(
            choices=preset_options, value="全部", label="Preset",
            scale=3, elem_classes=["history-filter-preset"],
        )
        status_filter = gr.Radio(
            choices=status_options, value="全部", label="状态",
            scale=4, elem_classes=["history-filter-status", "custom-pills"],
        )
        count_label = gr.Markdown(
            value="共 0 条", elem_classes=["history-count"],
        )
        refresh_btn = gr.Button("🔃 刷新", variant="secondary", scale=1)

    # 两栏:左 7 Dataframe / 右 5 详情
    with gr.Row():
        with gr.Column(scale=7, elem_classes=["history-list-col"]):
            df = gr.Dataframe(
                headers=["时间", "状态", "preset", "耗时", "prompt", "id"],
                # 第 2 列 (状态) 用 html 渲染,让 _run_row 返回的 badge 标签生效
                # (Gradio 6 默认把 HTML 当字符串 escape)
                datatype=["str", "html", "str", "str", "str", "str"],
                # 列宽按内容优先级: prompt 摘要最宽,id 最窄
                column_widths=["17%", "11%", "14%", "9%", "37%", "12%"],
                interactive=False, wrap=True,
                elem_classes=["custom-dataframe"],
            )
        with gr.Column(scale=5, elem_classes=["history-detail-col"]):
            detail_summary = gr.HTML(
                value="<div class='detail-empty'>选中一条记录查看详情</div>",
                elem_classes=["detail-summary-wrap"],
            )
            detail_media = gr.HTML(
                value="<div class='detail-empty'>—</div>",
                label="输出预览",
            )
            with gr.Accordion(
                "📝 提示词全文", open=False, elem_classes=["custom-accordion"]
            ):
                detail_prompt_md = gr.Markdown(value="")
            # 隐藏 manifest JSON 组件,专门给 rerun 用 (Gradio JSON 自动反序列化)
            detail_manifest = gr.JSON(value={}, visible=False)
            rerun_btn = gr.Button(
                "🔁 加载到运行", variant="primary",
                elem_classes=["btn-run-primary"],
            )

    # 三个事件源都触发同一个 handler
    # outputs: rows, summary_html, media_html, json_str, prompt_md, count_label
    event_outputs = [df, detail_summary, detail_media, detail_manifest, detail_prompt_md, count_label]
    event_inputs = [preset_filter, status_filter]
    refresh_btn.click(fn=_refresh_history_filtered, inputs=event_inputs, outputs=event_outputs)
    preset_filter.change(fn=_refresh_history_filtered, inputs=event_inputs, outputs=event_outputs)
    status_filter.change(fn=_refresh_history_filtered, inputs=event_inputs, outputs=event_outputs)

    # Rerun: 从历史记录加载到运行表单。点击后会:
    #   1. 切到"运行" tab (JS 前置器)
    #   2. 选中该 manifest 对应的 preset (会触发 wf_radio.change, 该 change 会调
    #      example_to_form_values, 但我们随后在 .then() 里用 manifest 覆盖默认值)
    #   3. 用 manifest 里的 prompt/sizes/seed/file 填表单
    def _stage_rerun(manifest):
        """Step 1: 选 preset + 跳过下次自动填表单。返回 manifest 给下一步。
        Tab 切换由 JS 前置器处理(gr.update(selected=...) 对 Tabs 不生效)。"""
        if not manifest:
            return gr.update(), gr.update()
        preset = manifest.get("preset") or "zimage"
        _SKIP_AUTO_LOAD.add(preset)
        return gr.update(value=preset), gr.update(value=manifest)

    def _fill_from_manifest(preset_name, manifest):
        """Step 2: 用 manifest 填表单。在 wf_radio.change 之后跑,覆盖 example 自动填。"""
        if not preset_name or not manifest:
            return [gr.update() for _ in _ALL_INPUTS_FLAT]
        target_values = _manifest_to_form_values(preset_name, manifest)
        result = []
        for name in _iter_preset_names():
            try:
                cfg = config.preset_config(name)
                n = len(cfg["user_facing_inputs"])
            except Exception:
                n = 0
            if name == preset_name:
                if len(target_values) < n:
                    target_values = target_values + [None] * (n - len(target_values))
                result.extend(target_values[:n])
            else:
                result.extend([gr.update() for _ in range(n)])
        return result

    if _TABS_REF is not None and _WF_RADIO_REF is not None and _ALL_INPUTS_FLAT:
        _rerun_js = """
(manifest) => {
  if (!manifest) return null;
  const tabs = document.querySelectorAll('button[role="tab"]');
  if (tabs && tabs.length > 0 && tabs[0]) tabs[0].click();
  return null;
}
"""
        rerun_btn.click(
            fn=_stage_rerun,
            inputs=[detail_manifest],
            outputs=[_WF_RADIO_REF, detail_manifest],
            js=_rerun_js,
        ).then(
            fn=_fill_from_manifest,
            inputs=[_WF_RADIO_REF, detail_manifest],
            outputs=_ALL_INPUTS_FLAT,
        )
    else:
        _log.warning("history rerun btn disabled: build_ui not yet wired (refs None)")

    return df, detail_manifest, detail_summary, detail_media, refresh_btn, rerun_btn



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
        value=_apply_combined(_DEFAULT_THEME_ID, _DEFAULT_MODE),
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
        value=_DEFAULT_THEME_ID,
        label="配色方案",
        elem_classes=["custom-radio"],
    )
    theme_desc = gr.Markdown(_get_theme_desc(_DEFAULT_THEME_ID))

    # === 模式切换 (auto / dark / light) ===
    mode_choices = [(m["name"], m["id"]) for m in _list_modes()]
    mode_radio = gr.Radio(
        choices=mode_choices,
        value=_DEFAULT_MODE,
        label="明暗模式",
        elem_classes=["custom-radio"],
    )
    mode_desc = gr.Markdown(_get_mode_desc(_DEFAULT_MODE))

    # 双 radio 互相感知:换主题时拿到当前 mode,反之亦然。
    # 用 _apply_combined 合并输出,保证 <style> 单块稳定。
    def _on_theme_change(new_tid: str, current_mode: str) -> tuple[str, str]:
        return _apply_combined(new_tid, current_mode), _get_theme_desc(new_tid)

    def _on_mode_change(new_mode: str, current_tid: str) -> tuple[str, str]:
        return _apply_combined(current_tid, new_mode), _get_mode_desc(new_mode)

    theme_radio.change(
        fn=_on_theme_change,
        inputs=[theme_radio, mode_radio],
        outputs=[theme_injector, theme_desc],
    )
    mode_radio.change(
        fn=_on_mode_change,
        inputs=[mode_radio, theme_radio],
        outputs=[theme_injector, mode_desc],
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


def _is_image_preset(preset_cfg):
    """preset 是文生图类（输出 image）还是视频类。"""
    return preset_cfg.get("output_kind") == "image" or preset_cfg.get("category") == "image"


def _render_preview_prompt_html(prompt: str, sizes: list) -> str:
    """把 example 的 prompt + sizes 渲染成右栏“示例预览”卡里要展示的 HTML。

    - sizes 在 prompt 之前一行小灰字,展示实际跑的尺寸
    - prompt 用 <pre> 等宽保留换行 + <details> 默认收起,避免长 prompt 占太多视觉空间
    """
    parts = []
    if sizes:
        parts.append(
            "<div style='font-size:12px;color:#6b7280;margin:0 0 6px'>"
            "📐 尺寸: " + chr(44).join(sizes) + "</div>",
        )
    if prompt:
        esc = prompt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(
            "<details>"
            "<summary style='cursor:pointer;font-size:12px;color:#9ba1a8'>"
            "📝 完整提示词(点击展开)</summary>"
            "<pre style='white-space:pre-wrap;font-size:12px;line-height:1.55;"
            "padding:10px;background:var(--block-background-fill,rgba(0,0,0,0.04));"
            "border-radius:6px;max-height:240px;overflow:auto;margin:8px 0 0'>"
            + esc + "</pre>" + "</details>",
        )
    return "".join(parts)

def _media_to_html(media, is_image: bool) -> str:
    """把 run 函数 yield 的 media 转成 HTML。

    - is_image=True 且 media 是 list → <img> 网格
    - is_image=True 且 media 是单 URL → <img>
    - is_image=False 且 media 是 http URL 或本地路径 → <video>
    - 未知 URL / 本地文件(扩展名不在 image/video 范围内)→ 出现路径+下载链接 banner,
      让用户知道文件已生成、可以去下载 — 这是"未知输出类型"的最小可用 fallback。

    直接用 ComfyUI /view URL(浏览器同机可访问),绕过 gr.Video 不支持外部 URL 的限制。
    """
    if not media:
        return "<div style=\"color:#6b7280;padding:20px\">等待结果...</div>"

    if is_image:
        if isinstance(media, list):
            if not media:
                return "<div style=\"color:#6b7280;padding:20px\">等待结果...</div>"
            imgs = "".join(
                "<img src=\"" + str(u) + "\" style=\"max-width:32%;margin:4px;border:1px solid #2a2d33;border-radius:8px\"/>"
                for u in media if u
            )
            return "<div style=\"padding:8px\">" + imgs + "</div>"
        return "<div style=\"padding:8px\"><img src=\"" + str(media) + "\" style=\"max-width:100%;border-radius:8px\"/></div>"

    # is_image=False
    src = media[0] if isinstance(media, list) else media
    if not src or not isinstance(src, str):
        return "<div style=\"color:#6b7280;padding:20px\">等待结果...</div>"

    low_src = src.lower()
    video_ext = (".mp4", ".mov", ".webm", ".gif")
    image_ext = (".png", ".jpg", ".jpeg", ".webp")

    # HTTP URL
    if src.startswith("http"):
        if low_src.endswith(video_ext):
            return ("<div style=\"padding:8px\"><video controls autoplay style=\"max-width:100%;border-radius:8px\">"
                    "<source src=\"" + src + "\"/></video></div>")
        if low_src.endswith(image_ext):
            return "<div style=\"padding:8px\"><img src=\"" + src + "\" style=\"max-width:100%;border-radius:8px\"/></div>"
        # 未知 HTTP 路径(可能 ComfyUI output 是 JSON / 3D / 等)
        return ("<div class=\"file-fallback\">📄 未知输出格式: <code>" + src[:80] + "</code></div>")

    # 本地路径
    from pathlib import Path as _P
    src_path = _P(src)
    if src_path.exists():
        try:
            rel = src_path.relative_to(config.REPO_ROOT)
            file_url = "/file=" + str(rel).replace(chr(92), "/")
            if low_src.endswith(video_ext):
                return ("<div style=\"padding:8px\"><video controls style=\"max-width:100%;border-radius:8px\">"
                        "<source src=\"" + file_url + "\"/></video></div>")
            if low_src.endswith(image_ext):
                return "<div style=\"padding:8px\"><img src=\"" + file_url + "\" style=\"max-width:100%;border-radius:8px\"/></div>"
            # 未知扩展名本地文件:显示 banner + 下载链接
            return ("<div class=\"file-fallback\">"
                    "📄 <b>" + src_path.name + "</b> 已生成。浏览器不能预览此格式,请点击下载: "
                    "<a href=\"" + file_url + "\" download>下载</a></div>")
        except ValueError:
            # 不在 REPO_ROOT 下
            return ("<div class=\"file-fallback\">"
                    "📄 <b>" + src_path.name + "</b> 已生成。路径: <code>" + src + "</code></div>")

    # 都不是
    return ("<div class=\"file-fallback\">"
            "📄 未知输出: <code>" + src[:80] + "</code></div>")


def _create_one_input(spec):
    """创建单个输入组件 + 紧跟的辅助元素（预览/随机按钮）。

    返回创建的组件（供调用方收集）。组件构造即注册到当前 Blocks 上下文，不调 .render()。
    """
    from app import prompts as prompts_mod
    typ = spec["type"]
    comp = _build_input_component(spec)
    if typ == "file:image":
        with gr.Row():
            preview = gr.Image(label="缩略图", height=180, interactive=False, show_label=False)
            comp.change(fn=lambda p: p if p else None, inputs=[comp], outputs=[preview])
    elif typ == "file:video":
        with gr.Row():
            preview_v = gr.Video(label="预览", height=180, interactive=False, autoplay=False, show_label=False)
            comp.change(fn=lambda p: p if p else None, inputs=[comp], outputs=[preview_v])
    elif typ == "prompt_pool":
        with gr.Row():
            rand_btn = gr.Button("🎲 随机提示词", variant="secondary", size="sm")
            rand3_btn = gr.Button("🎲 随机3条", variant="secondary", size="sm")
            rand_btn.click(fn=lambda: prompts_mod.random_prompt(), outputs=[comp])
            rand3_btn.click(
                fn=lambda: "\n---\n".join(prompts_mod.random_prompts(n=3)),
                outputs=[comp],
            )
    return comp


def _save_last_run(preset_name, values):
    """跑成功时把当前表单值写到 app/data/last_run/{preset_name}.json。

    与 app/data/runs/ 的 audit manifest 不重叠:manifest 是完整的运行记录,
    这里只存"上次成功跑的参数",给 UI 的"加载上次成功参数"按钮用,失败不写。
    
    values: gr input 组件的当前值列表(None / str / int / float / bool / list / dict)。
    gr.File 等非 JSON-native 组件会被序列化成 str(其路径)。
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
                # gr.File 等
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


_CATEGORY_ICON = {"video": chr(0x1F3AC), "image": chr(0x1F5BC) + chr(0xFE0F),
                  "audio": chr(0x1F50A), "3d": chr(0x1F9CA), "other": chr(0x1F4E6)}


def _category_icon(cat: str) -> str:
    return _CATEGORY_ICON.get(cat, chr(0x1F4E6))


def _yield_run_stream(
    run_fn,
    preset_name: str,
    vals: tuple,
    *,
    is_image: bool,
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
                _media_to_html(media, is_image),
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
            _media_to_html(last_media, is_image),
            gr.update(value=f"<div class='error-banner-inner'><b>运行异常</b><br>{exc!r}</div>", visible=True),
            gr.update(visible=False),
            gr.update(value="", visible=False),
            last_media,
        )

    yield (
        chr(10).join(log[-12:]),
        _media_to_html(last_media, is_image),
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
    is_image = _is_image_preset(preset_cfg)
    specs = preset_cfg["user_facing_inputs"]

    # [顶部] 工作流标题 + 简介
    gr.Markdown(
        f"### {preset_cfg.get('display_name', preset_name)}\n"
        f"<span style='color:#9ba1a8'>{preset_cfg.get('description', '')}</span>"
    )

    # ===== 第四阶段 §A：两栏工作台布局 =====
    # with gr.Row(equal_height=False) 包左右两栏:
    #   左控制栏 gr.Column(scale=5): basic 输入 + 高级参数 + 段数预估 + 示例按钮 + 🚀 开始运行
    #   右预览栏 gr.Column(scale=6): 📜 运行日志 + 错误条 + 结果区 + 🔁 再来 + 打开输出目录
    # 组件创建顺序保证: 左栏全部组件 → 右栏全部组件 (事件绑定在两栏关闭后才做,
    # 引用的都是已存在的组件对象,不受布局影响)。
    inputs_by_nid: dict[str, object] = {}
    basic_specs = [s for s in specs if s.get("tier", "basic") == "basic"]
    advanced_specs = [s for s in specs if s.get("tier") == "advanced"]

    with gr.Row(equal_height=False):
        # ============ 左控制栏 ============
        with gr.Column(scale=5):
            # [输入组件]
            # basic 组件按 user_facing_inputs 原始顺序渲染(不拆 file/param 两组),这样作者在
            # params.json 里把"抠图词"排在对应上传文件后面,UI 上就紧跟在一起 —— 例如
            # 参考图(30) → 参考图抠图词(362) → 驱动视频(369) → 驱动视频抠图词(348)。
            # advanced 组件仍折叠进"🔧 高级参数"。
            if basic_specs:
                with gr.Group(elem_classes=["step-card", "card-core"]):
                    gr.Markdown("**① 输入素材**")
                    for spec in basic_specs:
                        comp = _create_one_input(spec)
                        inputs_by_nid[str(spec["node_id"])] = comp

            if advanced_specs:
                with gr.Accordion("🔧 高级参数(一般不用改)", open=False, elem_classes=["custom-accordion"]):
                    for spec in advanced_specs:
                        comp = _create_one_input(spec)
                        inputs_by_nid[str(spec["node_id"])] = comp

            inputs = [inputs_by_nid[str(s["node_id"])] for s in specs]

            # 段数预估(仅视频类 preset)
            if not is_image:
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
                "🚀 开始运行", variant="primary", size="lg",
                elem_classes=["btn-run-primary"],
            )

        # ============ 右作品预览栏 ============
        with gr.Column(scale=6):
            # [示例预览] —— 当 preset 的 example 含 preview_image 时常驻展示,
            # 让用户在未运行前就能看到 "这个 preset 跑出来是什么样"。
            # 可见性由 preset 决定,与 ex_btn.click 无关(数据本身就是 preset 的)。
            _ex_cfg = preset_cfg.get("example") or {}
            _preview_image_raw = _ex_cfg.get("preview_image")
            # preview_image 可能是 http(s):// URL、项目内相对路径、或旧的 "/file=..." 写法。
            # Gradio 6.20 的 gr.Image 接受 PIL/ndarray/pathlib.Path/str(本地路径或 URL)。
            # 项目内路径走 config.REPO_ROOT 拼绝对;URL 直接传(走 http 拉取)。
            if _preview_image_raw and not _preview_image_raw.startswith(("http://", "https://")):
                if _preview_image_raw.startswith("/file="):
                    _rel = _preview_image_raw[len("/file="):].replace("/", __import__("os").sep)
                else:
                    _rel = _preview_image_raw.replace("/", __import__("os").sep)
                _preview_image_url = str(config.REPO_ROOT / _rel)
            else:
                _preview_image_url = _preview_image_raw
            _preview_caption = _ex_cfg.get("preview_caption", "")
            _preview_prompt = _ex_cfg.get("prompt", "")
            _preview_sizes = list(_ex_cfg.get("sizes") or [])
            _has_preview = bool(_preview_image_url)
            with gr.Group(visible=_has_preview, elem_classes=["card-core"]):
                gr.Markdown("**📷 示例预览**")
                _caption_md = gr.Markdown(value=_preview_caption, visible=bool(_preview_caption))
                _preview_img = gr.Image(
                    value=_preview_image_url,
                    show_label=False,
                    interactive=False,
                    elem_classes=["result-area"],
                )
                _prompt_html = gr.HTML(
                    value=_render_preview_prompt_html(_preview_prompt, _preview_sizes),
                    visible=bool(_preview_prompt or _preview_sizes),
                )

            # [运行日志] 折叠(默认收起,跑起来自动展开)
            with gr.Accordion("📜 运行日志", open=False, elem_classes=["custom-accordion"]):
                status_box = gr.Textbox(
                    value="等待运行,或点上方「加载示例素材」",
                    label="状态",
                    interactive=False,
                    lines=4, max_lines=10,
                )

            # [错误高亮] 默认隐藏
            error_box = gr.HTML(value="", visible=False, elem_classes=["error-banner"])

            # [生成结果]
            output_box = gr.HTML(
                value="<div style='color:#6b7280;padding:20px'>运行后这里显示结果</div>",
                elem_classes=["result-area"],
                label="生成结果",
            )

            # [次级操作] 🔁 用相同参数再来 (视觉降级, 不抢主按钮焦点)
            re_run_btn = gr.Button(
                "🔁 用相同参数再来",
                variant="secondary",
                size="lg",
                visible=False,
                elem_classes=["btn-run-secondary"],
            )

            # [打开输出目录]
            open_dir_msg = gr.Markdown(value="", visible=False)
            open_dir_btn = gr.Button("📂 打开 ComfyUI 输出目录", variant="secondary", size="sm")

    # === 事件绑定 ===
    run_fn = run_image_workflow if is_image else run_workflow
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

        def _on_done(_status_msg, _vals):
            _save_last_run(preset_name, _vals)
            last_btn.visible = True

        log_text = ""
        last_media = None
        try:
            for status_msg, media_html, err_upd, re_run_upd, open_dir_upd, last_media in _yield_run_stream(
                run_fn=run_fn,
                preset_name=preset_name,
                vals=vals,
                is_image=is_image,
                on_status_done=_on_done,
            ):
                log_text = status_msg
                yield (
                    status_msg,
                    media_html,
                    err_upd,
                    re_run_upd,
                    open_dir_upd,
                    _RUN_BTN_RUNNING,
                )
        finally:
            run_btn.interactive = True

        # 最终 yield:按钮切回 RESTING,media_html 用 last_media(若有),
        # 保留刚生成的图/视频,不要被 _media_to_html(None, ...) 覆盖成占位。
        yield (
            log_text,
            _media_to_html(last_media, is_image),
            gr.update(value="", visible=False),
            gr.update(visible=False),
            gr.update(value="", visible=False),
            _RUN_BTN_RESTING,
        )


    run_click_outputs = [status_box, output_box, error_box, re_run_btn, open_dir_msg, run_btn]
    run_btn.click(fn=_run_and_format, inputs=inputs, outputs=run_click_outputs)
    re_run_btn.click(fn=_run_and_format, inputs=inputs, outputs=run_click_outputs)

    if ex_btn is not None:
        ex_btn.click(fn=lambda: example_to_form_values(preset_name), outputs=inputs)

    def _fill_last_run():
        return _load_last_run(preset_name, len(inputs))
    last_btn.click(fn=_fill_last_run, outputs=inputs)

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

_TOKENS_CACHE: str | None = None
_THEMES_CACHE: list[dict] | None = None
_DEFAULT_THEME_ID = "coral-orange"
_DEFAULT_MODE = "auto"
_THEMES_PATH = config.REPO_ROOT / "app" / "presets" / "themes.json"
_TOKENS_PATH = config.REPO_ROOT / "app" / "static" / "tokens.css"

# 表面 / 文字 / 边框 token —— dark 是默认值已经在 :root 里写过了,
# 这里再存一份字符串常量供 _apply_mode / _apply_combined 动态注入。
# Light 值跟 @media (prefers-color-scheme: light) 块同源 —— 单次修改两处。
_DARK_SURFACE = """  --bg-app:        #0f1115;
  --bg-panel:      #15181e;
  --bg-card:       #1a1d23;
  --bg-card-hover: #1f232b;
  --bg-overlay:    #23272f;
  --bg-input:      #0c0e12;
  --border-subtle: #252830;
  --border-default: #2f333d;
  --border-strong:  #4b5160;
  --text-primary:   #f3f4f6;
  --text-secondary: #c2c7d2;
  --text-muted:     #8b909b;
  --text-faint:     #5f6470;
  --text-on-accent: #0f1115;"""

_LIGHT_SURFACE = """  --bg-app:        #f8f9fa;
  --bg-panel:      #ffffff;
  --bg-card:       #ffffff;
  --bg-card-hover: #f1f3f5;
  --bg-overlay:    rgba(241, 243, 245, 0.85);
  --bg-input:      #ffffff;
  --border-subtle: #e9ecef;
  --border-default: #dee2e6;
  --border-strong:  #adb5bd;
  --text-primary:   #212529;
  --text-secondary: #495057;
  --text-muted:     #6c757d;
  --text-faint:     #adb5bd;
  --text-on-accent: #ffffff;"""

_MODES: list[dict] | None = None


def _load_tokens_css() -> str:
    """读 app/static/tokens.css,缓存结果。文件不存在返回空串(不崩)。"""
    global _TOKENS_CACHE
    if _TOKENS_CACHE is None:
        try:
            _TOKENS_CACHE = _TOKENS_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            _TOKENS_CACHE = ""
    return _TOKENS_CACHE


def _list_themes() -> list[dict]:
    """读 app/presets/themes.json,返回 [{id, name, desc, tokens}, ...] 列表。"""
    global _THEMES_CACHE
    if _THEMES_CACHE is None:
        try:
            raw = json.loads(_THEMES_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            raw = {}
        out: list[dict] = []
        for tid, t in raw.items():
            out.append({
                "id": tid,
                "name": t.get("name", tid),
                "desc": t.get("desc", ""),
                "tokens": t.get("tokens", {}),
            })
        _THEMES_CACHE = out
    return _THEMES_CACHE


def _apply_theme(theme_id: str) -> str:
    """生成 <style>:root{...}</style> 用于主题注入。

    未知 theme_id 回落到默认主题 (coral-orange),不抛异常。
    """
    themes = {t["id"]: t for t in _list_themes()}
    theme = themes.get(theme_id) or themes.get(_DEFAULT_THEME_ID)
    if theme is None:
        # themes.json 都坏了 —— 至少返回一个空的 style 标签,不崩
        return "<style>:root{}</style>"
    decls = "\n".join(
        f"  {k}: {v};" for k, v in theme["tokens"].items()
    )
    return f"<style>:root {{\n{decls}\n}}</style>"


def _build_launch_css() -> str:
    """组装 launch(css=...) 的入参。包含 tokens.css 全文 + 默认主题 + 默认模式。

    返回**单个 CSS 字符串**(Gradio 6 的 launch(css=...) 签名是 str | None,
    不是 list)。Gradio 内部会用 CSSStyleSheet.replaceSync 解析这个字符串,
    再自己包 <style>; 必须是纯 CSS(不带 <style> 标签),且必须是 str 不是 list —
    早期版本误传 list[str] 导致 replaceSync 收到 object → 前端
    "e.replace is not a function" → 页面永远卡在"加载中"。

    默认 mode 是 "auto"(由浏览器 media query 决定),所以默认模式下
    surface override 是空的,不会跟 @media 块冲突。
    """
    tokens = _load_tokens_css()
    default_combined = _apply_combined(_DEFAULT_THEME_ID, _DEFAULT_MODE)
    # _apply_combined 返回 "<style>:root{...}</style>",剥掉 <style></style> 标签
    default_css = _strip_style_tag(default_combined)
    # 合并成单个字符串(Gradio 6 不接受 list)
    return f"{tokens}\n{default_css}"


def _strip_style_tag(html: str) -> str:
    """把 "<style>...</style>" 里的 CSS 内容剥出来。无标签时原样返回。"""
    import re as _re
    m = _re.match(r"\s*<style[^>]*>(.*)</style>\s*$", html, _re.S)
    return m.group(1) if m else html


def _get_theme_desc(tid: str) -> str:
    """按 theme_id 返回一行 markdown 描述。设置 tab 用。"""
    for t in _list_themes():
        if t["id"] == tid:
            return f"**{t['name']}** —— {t['desc']}"
    return ""


def _list_modes() -> list[dict]:
    """返回 3 档 mode: auto / dark / light。

    auto = 浏览器 prefers-color-scheme 决定 (默认)
    dark = 强行深色,无视系统设置
    light = 强行浅色,无视系统设置
    """
    global _MODES
    if _MODES is None:
        _MODES = [
            {"id": "auto", "name": "自动跟随系统", "desc": "跟随操作系统 prefers-color-scheme 设置"},
            {"id": "dark", "name": "暗黑模式", "desc": "强行深色皮肤,无视系统设置"},
            {"id": "light", "name": "明亮模式", "desc": "强行浅色皮肤,无视系统设置"},
        ]
    return _MODES


def _apply_mode(mode: str) -> str:
    """生成 surface / text / border 的 override <style>:root{}</style>。

    auto  → 空 style,让浏览器 media query 自己决定。
    dark  → 注入 _DARK_SURFACE,覆盖 :root 默认值。
    light → 注入 _LIGHT_SURFACE,覆盖 :root 默认值。
    未知 mode → 回落 auto。
    """
    if mode == "dark":
        body = _DARK_SURFACE.strip()
    elif mode == "light":
        body = _LIGHT_SURFACE.strip()
    else:
        body = ""  # auto / 未知模式
    return f"<style>:root {{\n{body}\n}}</style>"


def _apply_combined(theme_id: str, mode: str) -> str:
    """合并 accent + mode 覆盖为一个 <style> 块。

    合并到同一个 :root 而不是两个独立 <style>,保证属性覆盖顺序稳定。
    auto 模式只输出 accent block,不输出 surface block。
    """
    themes = {t["id"]: t for t in _list_themes()}
    theme = themes.get(theme_id) or themes.get(_DEFAULT_THEME_ID)
    accent_decls = ""
    if theme is not None:
        accent_decls = "\n  ".join(f"{k}: {v};" for k, v in theme["tokens"].items())

    if mode == "dark":
        surface_decls = _DARK_SURFACE.strip()
    elif mode == "light":
        surface_decls = _LIGHT_SURFACE.strip()
    else:
        surface_decls = ""

    parts = [p for p in (accent_decls, surface_decls) if p]
    body = "\n".join(parts)
    return f"<style>:root {{\n{body}\n}}</style>"


def _get_mode_desc(mode: str) -> str:
    """按 mode id 返回一行 markdown 描述。设置 tab 用。"""
    for m in _list_modes():
        if m["id"] == mode:
            return f"**{m['name']}** —— {m['desc']}"
    return ""


CSS = _build_launch_css()


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

    # Radio 显示用 label:加分类 emoji,方便浏览
    def _wf_label(w):
        cat = w.get("category", "other")
        icon = _category_icon(cat)
        suffix = f" · {cat}" if cat != "other" else ""
        return f"{icon} {w['display_name']}{suffix}"
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
        theme_injector = gr.HTML(value=_apply_theme(_DEFAULT_THEME_ID), visible=True, elem_id="theme-injector")

        with gr.Tabs() as main_tabs:
            with gr.Tab("运行"):
                with gr.Row():
                    # ============ LEFT COLUMN ============
                    with gr.Column(scale=1, min_width=220):
                        wf_search = gr.Textbox(
                            label="🔍 搜索",
                            placeholder="按名称筛选...",
                            show_label=False,
                            container=False,
                            max_lines=1,
                        )
                        gr.Markdown("## 🎬 工作流")
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

                        # ComfyUI 状态指示灯
                        comfy_status = gr.Markdown(_comfy_status_text())
                        with gr.Row():
                            refresh_status_btn = gr.Button("🔄 刷新状态", size="sm")
                            refresh_status_btn.click(
                                fn=_comfy_status_text,
                                outputs=[comfy_status],
                            )

                    # ============ RIGHT COLUMN ============
                    with gr.Column(scale=4):
                        # 关键改动:每个 preset 预渲染到自己 Group 里,通过 visibility 切换。
                        # 这样切换 workflow 时组件不被销毁,表单状态自动保留。
                        preset_panel_groups: dict[str, object] = {}
                        preset_inputs_map: dict[str, list] = {}
                        for wf in workflows:
                            with gr.Group(
                                visible=(wf["name"] == default_wf),
                                elem_id=f"panel-{wf['name']}",
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
                            result = []
                            for preset_name, _ins in preset_inputs_map.items():
                                if preset_name == name:
                                    if preset_name in _SKIP_AUTO_LOAD:
                                        _SKIP_AUTO_LOAD.discard(preset_name)
                                        # rerun 已经用 manifest 填表单了，跳过以免覆盖
                                        result.extend([gr.update() for _ in _ins])
                                    else:
                                        try:
                                            result.extend(example_to_form_values(preset_name))
                                        except Exception:
                                            result.extend([inp.value for inp in _ins])
                                else:
                                    # 非激活 preset:用 gr.update() 保持原状态,不触发变更
                                    result.extend([gr.update() for _ in _ins])
                            return result

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

                        gr.Markdown(
                            f"<small style='color:#6b7280'>"
                            f"限制: 参考图 ≤{config.MAX_IMAGE_MB}MB / 驱动视频 ≤{config.MAX_VIDEO_MB}MB / "
                            f"提示词 ≤{config.MAX_PROMPT_CHARS}字符 · 超时 {config.DEFAULT_TIMEOUT_SEC // 60} 分钟"
                            f"</small>"
                        )

            with gr.Tab("历史记录"):
                _build_history_tab()

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
        footer_links=[],
        enable_monitoring=False,
        allowed_paths=[config.REPO_ROOT / "app" / "static" / "examples"],
    )


if __name__ == "__main__":
    main()