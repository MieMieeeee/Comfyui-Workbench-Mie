"""workflow runner — 完整编排逻辑, 无 web 框架依赖.

stream_events(preset, form_values, on_success) 把 (status_msg, media) yield 流
包成 RunEvent, 供 Flask /api/run/<preset> 转 SSE.

业务依赖:
  - app.config / app.scail2_client / app.history
  - app.services.form_schema  (parse_sizes / estimated_segments / get_video_frames /
                               validate_inputs / _resolve_upload_name / _is_comfy_input_file)
  - app.services.status       (_extract_status_kind / _extract_step_progress)
  - app.services.media        (_media_to_html)
"""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from app import config
from app import history
from app import scail2_client
from app.workflow_validator import WorkflowValidationError
from app.scail2_client import ComfyUIError, ConnectionError_, ProtocolError_
from app.services import status as status_svc
from app.services import form_schema
from app.services.media import _media_to_html

_log = logging.getLogger("app.services.runner")


# ============================================================
# Gradio 替代品 (no-op / 异常)
# ============================================================

class _NoProgress:
    """替代 gr.Progress() — no-op, 调用 progress(x, desc=...) 不做任何事.

    Flask 版前端从 yield 的 status_msg 自行渲染进度, 不需要后端 progress 对象.
    """
    def __call__(self, *args, **kwargs):
        pass


class _RunError(Exception):
    """替代 gr.Error(msg) — 普通 Exception, 上层 stream_events 捕获后转 error event."""


# ============================================================
# RunEvent 数据类 + SSE 序列化
# ============================================================

@dataclass
class RunEvent:
    """SSE 事件数据类."""
    type: Literal["log", "media", "error", "done"]
    log: str | None = None
    status_msg: str | None = None
    media_url: str | None = None
    media_html: str | None = None
    error_html: str | None = None
    error_text: str | None = None  # 纯文本原始错误 (不含 HTML), 供前端复制按钮
    state: str | None = None
    elapsed_sec: float | None = None
    progress: tuple[int, int] | None = None

    def to_sse(self) -> str:
        d = asdict(self)
        if d.get("progress") is not None:
            d["progress"] = list(d["progress"])
        return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"


# ============================================================
# 辅助函数
# ============================================================

def _output_kind(preset_cfg) -> str:
    """根据 preset 配置推导输出类型: image | video | audio.

    薄包装 config.resolve_output_kind (review 2026-07-28 把 5 处重复推导统一到 config).
    保留模块级符号是因为早期测试 / 外部调用可能直接 import; 行为不变.
    """
    return config.resolve_output_kind(preset_cfg)


def _error_banner_html(title: str, raw_err: str) -> str:
    """统一构造 error banner: 状态标题 + 原始错误全文.

    不做分析, 不加 "下一步" 建议, 不截断 —— 用户要看完整原文并能复制.
    title 只是状态语义 (运行失败/超时/异常), 不是分析内容.
    """
    return f"<div class='error-banner-inner'><b>{title}</b><br>{raw_err}</div>"


# sca12 manifest 段数预估需要的三个 int 参数对应的 spec role.
# 老 runner 直接硬编码 node_id 367/464/479 取值; review 2026-07-28 改成读 spec 上的
# manifest_role 字段 (数据驱动), node_id 兜底保留给没迁移的老 preset.
# 注: 历史 479 (max_segments) 在当前 sca12 definition 里不是 user_facing_input,
#     所以 max_segments 永远走默认 0 (=不限制), 与旧行为一致.
_SEGMENT_ROLE_DEFAULTS = {
    "frames_per_segment": ("367", "value", 81),
    "pre_drop_frames": ("464", "value", 5),
    "max_segments": (None, None, 0),
}


def _resolve_segment_meta(inputs_spec, int_by_field):
    """从 inputs_spec 里按 manifest_role 解析 (fps, pre_drop, max_segments).

    每个 spec 可声明 "manifest_role": "frames_per_segment" | "pre_drop_frames" |
    "max_segments", runner 据此从 int_by_field 取值. 没声明 manifest_role 的 preset
    回退到老 node_id 兜底 (367/464), 行为跟重构前完全一致.
    """
    by_role = {}
    for spec in inputs_spec:
        role = spec.get("manifest_role")
        if role in _SEGMENT_ROLE_DEFAULTS:
            nid = str(spec["node_id"])
            field = spec.get("field", "value")
            default = _SEGMENT_ROLE_DEFAULTS[role][2]
            by_role[role] = int_by_field.get((nid, field), default)

    out = []
    for role in ("frames_per_segment", "pre_drop_frames", "max_segments"):
        if role in by_role:
            out.append(by_role[role])
            continue
        fallback_nid, fallback_field, default = _SEGMENT_ROLE_DEFAULTS[role]
        if fallback_nid is not None:
            out.append(int_by_field.get((fallback_nid, fallback_field), default))
        else:
            out.append(default)
    return out[0], out[1], out[2]


# manifest 的 prompt 三件套 (main/ref/drive) 对应的 spec role.
# 数据驱动收敛: 老 runner 硬编码 node_id 360/362/348 写 manifest, 非 SCAIL-2
# preset 的这些字段永远是空串. review 后改成读 spec.manifest_role (跟段数迁移
# _resolve_segment_meta 同款模式), 缺失时回退 SCAIL-2 老 node_id 兜底, 行为锁.
#
# 老 build_manifest 调用还有个 node_id 6 的 or 兜底 (replacements.get("6", ...)),
# 它是 SCAIL-2 之外某个文生图 preset 的 main prompt node —— 现在数据驱动路径会
# 先吃 manifest_role, 这个老兜底只在没声明 role 且没 360 时才生效.
_PROMPT_ROLE_DEFAULTS = {
    "main_prompt": ("360", "6"),
    "ref_prompt": ("362", None),
    "drive_prompt": ("348", None),
}


def _resolve_prompt_meta(
    inputs_spec, text_by_field: dict[tuple[str, str], str],
) -> tuple[str, str, str]:
    """从 inputs_spec 里按 manifest_role 解析 (main_prompt, ref_prompt, drive_prompt).

    每个 text/prompt_pool spec 可声明 "manifest_role" 为三者之一; 声明了就从
    text_by_field[(node_id, field)] 取值. 没声明 manifest_role 的 preset 回退到
    老 node_id 兜底 (360/362/348), 行为跟重构前完全一致.
    """
    by_role: dict[str, str] = {}
    for spec in inputs_spec:
        role = spec.get("manifest_role")
        if role in _PROMPT_ROLE_DEFAULTS:
            nid = str(spec["node_id"])
            field = spec.get("field", "text")
            by_role[role] = text_by_field.get((nid, field), "")

    out = []
    for role in ("main_prompt", "ref_prompt", "drive_prompt"):
        if role in by_role:
            out.append(by_role[role])
            continue
        primary_nid, secondary_nid = _PROMPT_ROLE_DEFAULTS[role]
        field = "text"
        val = text_by_field.get((primary_nid, field), "")
        if not val and secondary_nid is not None:
            val = text_by_field.get((secondary_nid, field), "")
        out.append(val)
    return out[0], out[1], out[2]


# ============================================================
# run_workflow — 视频/音频 preset 主流程
# ============================================================

def run_workflow(preset_name, *component_values):
    """运行指定 preset 的 workflow (video / audio 类).

    生成器 yield (status_msg, output_url) 流.
    """
    progress = _NoProgress()
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
    sizes_by_node: dict[str, Any] = {}
    model_by_field: dict[tuple[str, str], str] = {}
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
        elif typ == "file:audio":
            # VoiceClone 等场景: 参考音频走 file:audio, 复用 ref_name 槽位
            # (validate_inputs 用 ref_path 校验, 不区分 image/audio, 见 form_schema)
            file_by_type["audio"] = value
        elif typ == "image_sizes":
            sizes_by_node[nid] = value
        elif typ == "int":
            int_by_field[(nid, field)] = int(value) if value is not None else spec.get("default", 1)
        elif typ == "float":
            try:
                int_by_field[(nid, field)] = float(value) if value is not None else float(spec.get("default", 0.0))
            except (TypeError, ValueError):
                int_by_field[(nid, field)] = float(spec.get("default", 0.0))
        elif typ == "int_random":
            number = component_values[component_idx + 1] if component_idx + 1 < len(component_values) else spec.get("default", 0)
            int_by_field[(nid, field)] = random.randint(1, 10**12) if bool(value) else int(number)
            component_idx += 1
        elif typ == "model":
            # 模型参数: 一个动态下拉 (选项来自 /object_info). 值是 ComfyUI 模型文件名,
            # 直接当字符串 patch 进 loader 节点, 不走文本/数字桶.
            model_by_field[(nid, field)] = value or ""
        component_idx += 1
    ref_path = file_by_type.get("image")
    audio_path = file_by_type.get("audio")
    drive_path = file_by_type.get("video")
    size_by_node: dict[str, tuple[int, int]] = {}
    for spec in inputs_spec:
        if spec.get("type") != "image_sizes":
            continue
        parsed = form_schema.parse_sizes(sizes_by_node.get(str(spec["node_id"]), spec.get("default", [])))
        if not parsed:
            raise _RunError("尺寸格式无效: 请输入如 768x512 的宽x高")
        w, h = parsed[0]
        min_w, max_w = spec.get("min_width", 1), spec.get("max_width", 10000)
        min_h, max_h = spec.get("min_height", 1), spec.get("max_height", 10000)
        if not (min_w <= w <= max_w and min_h <= h <= max_h):
            raise _RunError(f"尺寸超出范围: {w}x{h}")
        size_by_node[str(spec["node_id"])] = (w, h)

    started_at = datetime.now(timezone.utc)
    prompt_id_final: str | None = None
    final_output: dict | None = None
    final_status = "failure"
    final_error: str | None = None

    err = form_schema.validate_inputs(ref_path, drive_path, preset_cfg, audio_path=audio_path)
    if err:
        _log.debug(f"validate fail: {err}")
        raise _RunError(err)
    _log.debug("validate pass")

    has_image_input = any(s.get("type") == "file:image" for s in inputs_spec)
    has_audio_input = any(s.get("type") == "file:audio" for s in inputs_spec)
    has_video_input = any(s.get("type") == "file:video" for s in inputs_spec)

    if has_image_input:
        progress(0.10, desc="上传参考图…")
        yield "⏳ [1/5] uploading reference image…", None
        try:
            ref_name = form_schema._resolve_upload_name(ref_path, kind="image")
        except (ComfyUIError, FileNotFoundError) as e:
            raise _RunError(str(e))
    if has_audio_input:
        # VoiceClone 等场景: 参考音频走 file:audio, 写到 ref_name (复用同一个上传槽位)
        progress(0.18, desc="上传参考音频…")
        yield "⏳ [2/5] uploading reference audio…", None
        try:
            ref_name = form_schema._resolve_upload_name(audio_path, kind="audio")
        except (ComfyUIError, FileNotFoundError) as e:
            raise _RunError(str(e))
    if has_video_input:
        progress(0.20, desc="上传驱动视频…")
        yield "⏳ [3/5] uploading drive video…", None
        try:
            drive_name = form_schema._resolve_upload_name(drive_path, kind="file")
        except (ComfyUIError, FileNotFoundError) as e:
            raise _RunError(str(e))

    progress(0.30, desc="组装 workflow…")
    yield "⏳ [3/5] loading + patching workflow…", None
    try:
        wf = scail2_client.load_workflow_template(preset_name)
        replacements: dict[str, dict[str, Any]] = {}
        for nid, fields in (preset_cfg.get("fixed_patches") or {}).items():
            replacements[nid] = dict(fields)
        for spec in inputs_spec:
            nid = str(spec["node_id"])
            field = spec["field"]
            typ = spec["type"]
            if typ == "file:image":
                if nid in replacements:
                    replacements[nid][field] = ref_name
                else:
                    replacements[nid] = {field: ref_name}
            elif typ == "file:video":
                if nid in replacements:
                    replacements[nid][field] = drive_name
                else:
                    replacements[nid] = {field: drive_name}
                for _extra in (spec.get("also_patch") or []):
                    _enid = str(_extra["node_id"])
                    _efield = _extra["field"]
                    if _enid in replacements:
                        replacements[_enid][_efield] = drive_name
                    else:
                        replacements[_enid] = {_efield: drive_name}
            elif typ == "file:audio":
                # 参考音频: 写到 LoadAudio 节点的 audio 字段 (纯文件名)
                # ref_name 在 has_audio_input 分支已被上传/解析过
                if nid in replacements:
                    replacements[nid][field] = ref_name
                else:
                    replacements[nid] = {field: ref_name}
                # file:audio 也支持 also_patch (例如把同一份音频同时写到别的 LoadAudio 节点)
                for _extra in (spec.get("also_patch") or []):
                    _enid = str(_extra["node_id"])
                    _efield = _extra["field"]
                    if _enid in replacements:
                        replacements[_enid][_efield] = ref_name
                    else:
                        replacements[_enid] = {_efield: ref_name}
            elif typ in ("text", "prompt_pool", "select"):
                raw = text_by_field.get((nid, field), "")
                final = (raw or "").strip() or (spec.get("default") or config.DEFAULT_PROMPT_TEXT)
                if nid in replacements:
                    replacements[nid][field] = final
                else:
                    replacements[nid] = {field: final}
                for _extra in (spec.get("mirror_to") or spec.get("also_patch") or []):
                    _enid = str(_extra["node_id"])
                    _efield = _extra["field"]
                    if _enid in replacements:
                        replacements[_enid][_efield] = final
                    else:
                        replacements[_enid] = {_efield: final}
            elif typ == "model":
                # 模型覆盖: 用用户选的文件名, 没选/空 → 退 spec.default (= 工作流自带模型).
                # 不用 DEFAULT_PROMPT_TEXT 兜底 (那是提示词, 塞进模型字段会把运行打挂).
                raw = model_by_field.get((nid, field), "")
                final = (raw or "").strip() or spec.get("default") or ""
                if final:
                    if nid in replacements:
                        replacements[nid][field] = final
                    else:
                        replacements[nid] = {field: final}
            elif typ == "image_sizes":
                w, h = size_by_node[str(spec["node_id"])]
                replacements.setdefault(nid, {}).update({"width": w, "height": h, "batch_size": 1})
            elif typ in ("int", "int_random"):
                default = spec.get("default", 1)
                val = int_by_field.get((nid, field), default)
                if nid in replacements:
                    replacements[nid][field] = val
                else:
                    replacements[nid] = {field: val}
            elif typ == "float":
                default = spec.get("default", 0.0)
                val = int_by_field.get((nid, field), default)
                if nid in replacements:
                    replacements[nid][field] = val
                else:
                    replacements[nid] = {field: val}
        patched = scail2_client.patch_workflow(
            wf, replacements, preset_config=preset_cfg, validate_after=True,
        )
    except (WorkflowValidationError, FileNotFoundError) as e:
        raise _RunError(str(e))

    progress(0.40, desc="入队 ComfyUI…")
    yield "⏳ [4/5] queuing prompt to ComfyUI…", None
    try:
        prompt_id, client_id = scail2_client.queue_prompt(patched)
    except (ComfyUIError, ProtocolError_) as e:
        raise _RunError(str(e))
    prompt_id_final = prompt_id
    yield f"⏳ [4/5] queued: {prompt_id[:8]}…", None

    video_url = None
    progress(0.45, desc="等待 ComfyUI 执行…")
    yield "⏳ [5/5] waiting for ComfyUI execution…", None
    _wait_p = 0.45
    _title_map = scail2_client.build_node_title_map(patched)
    _pq = scail2_client.start_progress_listener(client_id)
    try:
        for status_msg in scail2_client.wait_for_completion(
            prompt_id, title_map=_title_map, progress_queue=_pq,
        ):
            _step = status_svc._extract_step_progress(status_msg)
            if _step is not None:
                _ratio = _step[0] / _step[1]
                _wait_p = min(0.92, 0.45 + _ratio * (0.92 - 0.45))
            else:
                _wait_p = min(0.92, _wait_p + 0.02)
            progress(_wait_p, desc=status_msg.lstrip("⏳✅❌⏰ ").strip()[:40] or "执行中…")
            if status_msg.startswith("✅"):
                try:
                    hist = scail2_client.get_history(prompt_id)
                    if output_kind == "image":
                        image_outputs = scail2_client.extract_all_image_outputs(hist or {})
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
                        video_url = view_url
                except Exception as e:
                    status_msg = f"{status_msg} (拉 outputs 失败: {e})"
            kind, err = status_svc._extract_status_kind(status_msg)
            if kind is not None:
                final_status = kind
                if err:
                    final_error = err
            yield status_msg, video_url
            if status_msg.startswith(("✅", "❌", "⏰")):
                break
    finally:
        _pq.put(None)

    if final_status == "success":
        progress(1.0, desc="完成")
    else:
        progress(0, desc=f"❌ {final_status}")

    finished_at = datetime.now(timezone.utc)
    if prompt_id_final:
        try:
            fps, pre, mx = _resolve_segment_meta(inputs_spec, int_by_field)
            video_frames = form_schema.get_video_frames(drive_path) if drive_path else None
            est_seg = form_schema.estimated_segments(video_frames, fps, pre, max_segments=mx) if video_frames else None
            # manifest 的 prompt 字段从 spec.manifest_role 解析 (数据驱动),
            # 缺失时 _resolve_prompt_meta 内部回退 SCAIL-2 老 node_id 兜底.
            main_p, ref_p, drive_p = _resolve_prompt_meta(inputs_spec, text_by_field)
            manifest = history.build_manifest(
                prompt_id=prompt_id_final,
                started_at_iso=started_at.isoformat(),
                finished_at_iso=finished_at.isoformat(),
                duration_sec=int((finished_at - started_at).total_seconds()),
                preset=preset_name,
                reference_image=Path(ref_path).name if ref_path else "",
                drive_video=Path(drive_path).name if drive_path else "",
                prompt_text=main_p,
                frames_per_segment=fps,
                pre_drop_frames=pre,
                max_segments=mx,
                video_frames=video_frames,
                estimated_segments=est_seg,
                status=final_status,
                cache_hit=False,
                output=final_output,
                error=final_error,
                ref_prompt=ref_p,
                drive_prompt=drive_p,
                main_prompt=main_p,
            )
            history.write_manifest(manifest)
            _log.debug(f"manifest written: {prompt_id_final[:8]}, est_seg={est_seg}")
        except Exception as e:
            _log.error(f"manifest write failed: {e}")


# ============================================================
# run_image_workflow — 文生图 preset 主流程 (多尺寸循环)
# ============================================================

def run_image_workflow(preset_name, *component_values):
    """文生图 workflow (zimage 等纯图像 preset)."""
    progress = _NoProgress()
    _log.info(f"[run_image] ENTRY preset={preset_name}, {len(component_values)} values")
    yield "[READY] preparing image gen…", None

    preset_cfg = config.preset_config(preset_name)
    inputs_spec = preset_cfg["user_facing_inputs"]

    # 防御性断言: 本函数只处理纯文生图 (text/image_sizes/int_random/int/float).
    # 含 file 类输入 (图生图 / 视频生图) 必须走 run_workflow, 否则参考图被静默
    # 丢弃. stream_events 已对路由做了同样判定, 这里再断言一次防未来回归 ——
    # AGENTS.md "不要加半个能用的 type": 静默吞不如显式报.
    bad_types = sorted({
        str(s.get("type", "")) for s in inputs_spec
        if str(s.get("type", "")).startswith("file:")
    })
    if bad_types:
        raise _RunError(
            f"run_image_workflow 不支持 file 类输入 ({bad_types}), "
            f"该 preset 应走 run_workflow. 检查 stream_events 路由条件."
        )

    prompt_text = None
    sizes_raw = None
    seed_val = 0
    prompt_target: tuple[str, str] | None = None
    sizes_node_id = None
    # 收集所有 text / prompt_pool / select 字段, 避免多 text preset (e.g. QwenImage 的
    # positive + negative) 只 patch 最后一个, 前面那个被吞掉. 修 review 2026-07-29.
    text_patches: dict[tuple[str, str], str] = {}
    # 模型参数类 (zimage/qwen_image 等 T2I 工作流也要能换 unet/vae/clip): 解析时收齐,
    # 每个尺寸的 replacements 都带上 (模型与尺寸无关, 跨尺寸不变).
    model_patches: dict[tuple[str, str], str] = {}
    # int / float 字段原样 patch (不再当 seed 处理 —— seed 只由 int_random 负责).
    int_patches: dict[tuple[str, str], int] = {}
    float_patches: dict[tuple[str, str], float] = {}
    # seed 槽位: (node_id, field). int_random 每个尺寸重算一次 seed.
    seed_slot: tuple[str, str] | None = None
    # 两个计数器必须分开走:
    #   si —— user_facing_inputs 里的位置 (spec 顺序)
    #   vi —— component_values (扁平表单值) 里的位置, int_random 占 2 格 (随机勾 + 数值)
    # 之前只用一个 i: int_random 时 i += 2 把紧跟其后的那个 spec 整个跳过去了, 后面
    # 所有字段的值都往前错一格 —— Z-Image-Turbo 的 VAE 收到 unet 的文件名, ComfyUI 直接
    # 400 (issue #1).  spec 索引和表单值索引是两套坐标系, 不能混用.
    si = 0
    vi = 0
    while si < len(inputs_spec):
        spec = inputs_spec[si]
        typ = spec["type"]
        nid = str(spec["node_id"])
        if typ in ("text", "prompt_pool", "select"):
            value = component_values[vi] if vi < len(component_values) else None
            text_patches[(nid, spec["field"])] = value or ""
            # 第一个 text / prompt_pool 当主 prompt 喂 size loop, 其它的从 text_patches 出
            if typ in ("text", "prompt_pool") and prompt_target is None:
                prompt_text = value or ""
                prompt_target = (nid, spec["field"])
            si += 1
            vi += 1
        elif typ == "image_sizes":
            sizes_raw = component_values[vi] if vi < len(component_values) else None
            sizes_node_id = nid
            si += 1
            vi += 1
        elif typ == "int_random":
            randomize = bool(component_values[vi]) if vi < len(component_values) else True
            number_val = component_values[vi + 1] if vi + 1 < len(component_values) else spec.get("default", 0)
            seed_val = 0 if randomize else int(number_val) if number_val is not None else spec.get("default", 0)
            seed_slot = (nid, spec.get("field", "seed"))
            si += 1
            vi += 2
        elif typ == "int":
            raw = component_values[vi] if vi < len(component_values) else None
            int_patches[(nid, spec["field"])] = int(raw) if raw is not None else int(spec.get("default", 0))
            si += 1
            vi += 1
        elif typ == "float":
            raw = component_values[vi] if vi < len(component_values) else None
            try:
                float_patches[(nid, spec["field"])] = float(raw) if raw is not None else float(spec.get("default", 0.0))
            except (TypeError, ValueError):
                float_patches[(nid, spec["field"])] = float(spec.get("default", 0.0))
            si += 1
            vi += 1
        elif typ == "model":
            value = component_values[vi] if vi < len(component_values) else None
            model_patches[(nid, spec["field"])] = (value or "").strip() or str(spec.get("default") or "")
            si += 1
            vi += 1
        else:
            si += 1
            vi += 1

    # 主 prompt 缺省: 优先用 text_patches 里第一个非空值, 都没有再用 spec[0].default
    # (老逻辑直接抓 spec[0].default, 在多 text preset + user 给空 negative 的场景下
    # 会把空 positive fallback 成 example positive, 用户看到的输出是 example 的图)
    if not (prompt_text or "").strip():
        for (nid, field), val in text_patches.items():
            if val.strip():
                prompt_text = val
                prompt_target = (nid, field)
                break
        else:
            prompt_text = preset_cfg.get("user_facing_inputs", [{}])[0].get("default", "Photorealistic, ultra-detailed.")

    sizes = form_schema.parse_sizes(sizes_raw)
    if not sizes:
        sizes = [(1024, 1024)]
    _log.debug(f"[run_image] prompt_len={len(prompt_text)} sizes={sizes} seed={seed_val}")

    started_at = datetime.now(timezone.utc)
    prompt_ids: list[str] = []
    all_outputs: list[dict] = []
    final_status = "success"
    final_error: str | None = None
    final_failed_size: str | None = None  # 失败的 (w x h), 让最终提示说人话
    final_failed_idx: int | None = None    # 1-indexed 位置, 让用户定位批处理里哪张失败
    gallery_urls: list[str] = []

    try:
        wf_base = scail2_client.load_workflow_template(preset_name)
    except (FileNotFoundError, WorkflowValidationError) as e:
        raise _RunError(str(e))
    _title_map = scail2_client.build_node_title_map(wf_base)

    yield f"⏳ 准备生成 {len(sizes)} 张图…", None

    progress(0.05, desc=f"准备生成 {len(sizes)} 张图…")

    for idx, (w, h) in enumerate(sizes, 1):
        actual_seed = seed_val if seed_val and seed_val > 0 else random.randint(1, 10**12)
        replacements = {}
        # 把所有 text / prompt_pool / select 字段 patch 进去 (review 2026-07-29 修多 text 支持)
        for (nid, field), val in text_patches.items():
            if nid in replacements:
                replacements[nid][field] = val
            else:
                replacements[nid] = {field: val}
        # 模型覆盖 (与尺寸无关, 每张都带)
        for (nid, field), val in model_patches.items():
            if not val:
                continue
            if nid in replacements:
                replacements[nid][field] = val
            else:
                replacements[nid] = {field: val}
        # int / float 字段原样 patch (SAM3 threshold 之类)
        for (nid, field), val in int_patches.items():
            replacements.setdefault(nid, {})[field] = val
        for (nid, field), val in float_patches.items():
            replacements.setdefault(nid, {})[field] = val
        if seed_slot:
            replacements.setdefault(seed_slot[0], {})[seed_slot[1]] = actual_seed
        if sizes_node_id:
            replacements.setdefault(sizes_node_id, {}).update(
                {"width": w, "height": h, "batch_size": 1})

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
            raise _RunError(str(e))

        _seg_pq = scail2_client.start_progress_listener(client_id)
        _seg_p = seg_start
        try:
            for status_msg in scail2_client.wait_for_completion(
                prompt_id, title_map=_title_map, progress_queue=_seg_pq,
            ):
                kind, err = status_svc._extract_status_kind(status_msg)
                if kind == "failure":
                    final_status = "failure"
                    if err:
                        final_error = err
                    if final_failed_idx is None:
                        final_failed_idx = idx
                        final_failed_size = f"{w}x{h}"
                elif kind == "timeout":
                    final_status = "timeout"
                    if final_failed_idx is None:
                        final_failed_idx = idx
                        final_failed_size = f"{w}x{h}"
                _step = status_svc._extract_step_progress(status_msg)
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
            _seg_pq.put(None)

        if kind in ("failure", "timeout"):
            # 失败/超时后继续跑下一张尺寸 (尽力而为: 让用户拿到能跑通的那几张,
            # 而不是一张挂了整批全废). final_status / final_error / final_failed_idx
            # 已在上面记录, 末尾 yield 会告诉用户具体哪张失败.
            continue
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
        yield f"🖼 [{idx}/{len(sizes)}] {w}x{h} done", list(gallery_urls)

    finished_at = datetime.now(timezone.utc)
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
            seed=seed_val,
            sizes=[f"{w}x{h}" for w, h in sizes],
        )
        manifest["outputs"] = all_outputs
        manifest["prompt_ids"] = prompt_ids
        history.write_manifest(manifest)
        _log.debug(f"[run_image] manifest written, {len(all_outputs)} outputs")
    except Exception as e:
        _log.error(f"[run_image] manifest write failed: {e}")

    # 失败/超时最终提示: 必须告诉用户具体错误, 不能光说 'failure' 或 '全部完成' 糊弄.
    # 用户场景: ComfyUI 抛 torch.AcceleratorError: CUDA error: no kernel image is available ...
    # 之前我们抓了 final_error 但 yield 时丢掉, 用户看 '❌ 全部完成，failure' 不知道哪类错.
    if final_status == "success":
        progress(1.0, desc="完成")
        yield f"✅ 全部完成，共 {len(all_outputs)} 张图", list(gallery_urls)
    elif final_status == "failure":
        progress(0, desc="❌ 失败")
        # 只显示原始错误全文, 不截断, 不加位置/尺寸前缀 (用户明确要看原文 + 复制).
        _err = (final_error or "未知错误").strip()
        yield f"❌ {_err}", list(gallery_urls)
    else:  # timeout
        progress(0, desc="⏰ 超时")
        _err = (final_error or "").strip()
        yield f"⏰ 超时: {_err}" if _err else "⏰ 超时", list(gallery_urls)


# ============================================================
# stream_events — 把 run_workflow / run_image_workflow 包成 RunEvent 流
# ============================================================

def stream_events(
    preset_name: str,
    form_values: list,
    *,
    on_success: callable = None,
) -> Iterator[RunEvent]:
    """运行 preset, yield RunEvent 流. 末尾必有 'done' 事件.

    on_success(name, vals) 在成功时调用, 用于持久化 last_run.
    """
    preset_cfg = config.preset_config(preset_name)
    output_kind = _output_kind(preset_cfg)
    # run_image_workflow 是 zimage 那种多尺寸循环专用, 只支持 text / image_sizes /
    # int_random / int / float 五种类型. 它的 else 分支会静默丢弃 file 类输入, 所以
    # 含 file:image / file:video / file:audio 的 preset 必须走通用 run_workflow, 否则
    # 参考图等输入被默默忽略 (review: 之前路由只看 output_kind+image_sizes, 图生图
    # preset 会被错路由到 run_image_workflow). 通用 run_workflow 已支持 image
    # output_kind (见 wait_for_completion 后 extract_all_image_outputs 分支) + 全部 type.
    inputs = preset_cfg.get("user_facing_inputs", [])
    has_image_sizes = any(s.get("type") == "image_sizes" for s in inputs)
    has_file_input = any(
        str(s.get("type", "")).startswith("file:") for s in inputs
    )
    run_fn = (
        run_image_workflow
        if (output_kind == "image" and has_image_sizes and not has_file_input)
        else run_workflow
    )

    log_lines: list[str] = []
    last_media = None
    final_state = "failure"
    start_ts = time.monotonic()

    def _elapsed() -> float:
        return time.monotonic() - start_ts

    try:
        for status_msg, media in run_fn(preset_name, *form_values):
            log_lines.append(status_msg)
            if media:
                last_media = media

            kind, err = status_svc._extract_status_kind(status_msg)
            if kind == "success":
                final_state = "success"
                state = "success"
            elif kind == "failure":
                final_state = "failure"
                state = "failure"
            elif kind == "timeout":
                final_state = "timeout"
                state = "timeout"
            else:
                state = "running"

            step = status_svc._extract_step_progress(status_msg)
            error_html = None
            if kind == "failure":
                error_html = _error_banner_html("运行失败", err)
            elif kind == "timeout":
                error_html = _error_banner_html("运行超时", err)

            media_html = None
            if media:
                media_html = _media_to_html(media, output_kind)

            event_type = "media" if media_html else ("error" if error_html else "log")
            yield RunEvent(
                type=event_type,
                log="\n".join(log_lines[-12:]),
                status_msg=status_msg,
                media_url=str(media) if media else None,
                media_html=media_html,
                error_html=error_html,
                error_text=err,
                state=state,
                elapsed_sec=_elapsed(),
                progress=step,
            )

            if kind == "success" and on_success is not None:
                try:
                    on_success(preset_name, form_values)
                except Exception as e:
                    _log.warning(f"on_success callback failed: {e}")

            if kind in ("success", "failure", "timeout"):
                break

    except _RunError as exc:
        # run_workflow 里的 _RunError (原 gr.Error) -> error event
        _log.warning(f"_RunError: {exc}")
        err_msg = str(exc) or repr(exc)
        log_lines.append("❌ " + err_msg)
        yield RunEvent(
            type="error",
            log="\n".join(log_lines[-12:]),
            status_msg="❌ " + err_msg,
            error_html=_error_banner_html("运行失败", err_msg),
            error_text=err_msg,
            state="failure",
            elapsed_sec=_elapsed(),
        )
    except Exception as exc:
        _log.exception("stream_events exception: %s", exc)
        err_msg = str(exc) or repr(exc)
        log_lines.append("❌ " + err_msg)
        yield RunEvent(
            type="error",
            log="\n".join(log_lines[-12:]),
            status_msg="❌ " + err_msg,
            error_html=_error_banner_html("运行异常", err_msg),
            error_text=err_msg,
            state="failure",
            elapsed_sec=_elapsed(),
        )

    # done 事件
    final_media_html = None
    if last_media:
        final_media_html = _media_to_html(last_media, output_kind)
    yield RunEvent(
        type="done",
        log="\n".join(log_lines[-12:]),
        media_html=final_media_html,
        media_url=str(last_media) if last_media else None,
        state=final_state,
        elapsed_sec=_elapsed(),
    )
