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
    """校验 user_facing_inputs 里的 file:image / file:video 是否合规。

    - 只校验 preset 实际声明的 file type (audit by user_facing_inputs)。
      音频类 preset (qwen3_tts / ace_step_15_music) 没有 file inputs, 跳过整段校验。
    - 历史上先无条件校验 ref/drive, 但加 audio preset 后不能继续这样 (audio 无 file)。
    """
    has_image_input = any(s.get("type") == "file:image" for s in preset_cfg.get("user_facing_inputs", []))
    has_video_input = any(s.get("type") == "file:video" for s in preset_cfg.get("user_facing_inputs", []))
    if has_image_input:
        if not ref_path:
            return "参考图未上传"
        ext = _file_extension(ref_path)
        if ext not in config.ALLOWED_IMAGE_EXT:
            return f"参考图扩展名不支持: {ext}（允许: {sorted(config.ALLOWED_IMAGE_EXT)}）"
        if _file_size_mb(ref_path) > config.MAX_IMAGE_MB:
            return f"参考图过大: {_file_size_mb(ref_path):.1f}MB（上限 {config.MAX_IMAGE_MB}MB）"
    if has_video_input:
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


def example_to_form_values(preset_name):
    """把 preset 的 example 字典映射回表单值列表（按 user_facing_inputs 顺序）。

    给 UI 的"加载示例"按钮用：点击后一次性填好整个表单。
    映射规则（按 spec 的 type，不再按 node_id 硬编码）：
    - file:image → example["reference_image"]（解析成绝对路径，见 _resolve_example_file）
    - file:video → example["drive_video"]
    - prompt_pool → example["prompt"]
    - image_sizes → example["sizes"]
    - int_random → example["seed"]（拆成 [Checkbox, Number] 两个值）
    - 其它 → spec 的 example_key 字段（在 params.json 该 spec 上显式声明）
            找不到时退 spec.default

    数据驱动契约 (review 2026-07-14):
      text 类 spec 必须在 params.json 上显式写 "example_key": "<example 字典里的 key>",
      不再靠 node_id 隐式兜底。锁这条契约的是
      tests/test_preset_must_have_example.py::test_every_basic_text_input_is_explicitly_backed_by_example.

    重要：文件槽位必须返回**绝对路径**。gr.File(type='filepath').postprocess 会对
    纯文件名调 Path(name).stat()，文件在 COMFY_INPUT_DIR 不在 CWD → FileNotFoundError
    → 整个表单更新静默失败。所以这里拼成 COMFY_INPUT_DIR 下的绝对路径。
    运行时 _resolve_upload_name 已能识别 COMFY_INPUT_DIR 的文件跳过上传。
    """
    cfg = config.preset_config(preset_name)
    ex = cfg.get("example", {})
    values = []
    for spec in cfg["user_facing_inputs"]:
        typ = spec.get("type")
        if typ == "file:image":
            values.append(_resolve_example_file(ex.get("reference_image")))
        elif typ == "file:video":
            values.append(_resolve_example_file(ex.get("drive_video")))
        elif typ == "prompt_pool":
            values.append(ex.get("prompt", spec.get("default", "")))
        elif typ == "image_sizes":
            values.append(list(ex.get("sizes") or spec.get("default") or []))
        elif typ == "int_random":
            # int_random 在 UI 里是 [Checkbox, Number] 两组件,这里也要返回 2 个值:
            #  - Checkbox state: example 给具体 seed 时不勾(=固定), 否则按 random_default
            #  - Number value:   example.seed 的具体值或 spec.default
            ex_seed = ex.get("seed")
            if ex_seed is not None and ex_seed != 0:
                values.append(False)        # 不勾 = 固定
                values.append(ex_seed)
            else:
                values.append(bool(spec.get("random_default", True)))
                values.append(spec.get("default", 0))
        else:
            # 显式 example_key 优先, 其次 spec["field"], 再退 spec.default.
            # 数据驱动: 当 spec.field 名跟 example 里的 key 不一致时 (例如 ltx_23_i2v 的正向 prompt
            # spec.field="text" 而 example 里叫 "prompt"), 在 params.json 该 spec 上加 example_key 即可。
            # 这个例外的 fallback 链只走 user-provided example_key + spec.field, 不去猜通用 prompt key,
            # 防止负向提示词等不相关 spec 被错误填充。
            example_key = spec.get("example_key", spec.get("field", ""))
            v = ex.get(example_key)
            if v is None:
                v = spec.get("default")
            values.append(v)
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
        typ = spec.get("type")
        if typ == "file:image":
            values.append(_resolve_example_file(manifest.get("reference_image", "")))
        elif typ == "file:video":
            values.append(_resolve_example_file(manifest.get("drive_video", "")))
        elif typ == "prompt_pool":
            values.append(manifest.get("prompt_text", spec.get("default", "")))
        elif typ == "image_sizes":
            sizes = manifest.get("sizes")
            values.append(list(sizes or spec.get("default") or []))
        elif typ == "int_random":
            seed = manifest.get("seed")
            # manifest 只存最终 seed 值, 没有 "是否随机" 状态。回退规则:
            # 有具体 seed -> 不勾 Checkbox (=固定值)
            # 没 seed     -> 勾 Checkbox (=随机, 实际跑时随机生成)
            if seed is not None:
                values.append(False)
                values.append(seed)
            else:
                values.append(bool(spec.get("random_default", True)))
                values.append(spec.get("default", 0))
        else:
            # 跟 example_to_form_values 对称: 用 spec.example_key 从 manifest 取值,
            # 找不到退 spec.default. manifest 的 key 名与 example 一致 (history.py
            # 写入 ref_prompt / drive_prompt / main_prompt / frames_per_segment 等)。
            # 老 manifest 只存了 prompt_text 折叠版, 没有 main_prompt 时回退它, 再退 default。
            example_key = spec.get("example_key", spec.get("field", ""))
            v = manifest.get(example_key)
            if v is None and example_key in ("main_prompt", "prompt"):
                v = manifest.get("prompt_text")
            if v is None:
                v = spec.get("default")
            values.append(v)
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


# 匹配 wait_for_completion yield 的 running 消息里的 "value/max" step 进度
# (P0 之后格式: "⏳ MM:SS  running…  KSampler 12/20")。
# 注意: 时间戳是 MM:SS (冒号), 不会误匹配这个斜杠模式。
_STEP_PROGRESS_RE = _re.compile(r"(\d+)/(\d+)(?!\d)")


def _extract_step_progress(status_msg: str) -> tuple[int, int] | None:
    """从 status_msg 抽 step 进度 (value, max), 无则 None。

    用于 P2: 把 wait_for_completion yield 的 "12/20" 抽出来喂 gr.Progress,
    让顶部固定进度条跟状态条的真实 step 一致 (不再 _wait_p += 0.02 匀速假进度)。

    取 msg 里最后一个 value/max (max>0); 时间戳 MM:SS 用冒号不会误匹配。
    max=0 视为异常 (除零风险) -> None。
    """
    matches = _STEP_PROGRESS_RE.findall(status_msg)
    for value_str, max_str in reversed(matches):
        try:
            v, mx = int(value_str), int(max_str)
        except ValueError:
            continue
        if mx > 0:
            return (v, mx)
    return None


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
        progress(0.10, desc="上传参考图...")
        yield "⏳ [1/5] uploading reference image...", None
        try:
            ref_name = _resolve_upload_name(ref_path, kind="image")
        except (ComfyUIError, FileNotFoundError) as e:
            gr.Error(str(e))
            progress(0, desc=f"❌ 上传失败: {e}")
            yield f"❌ upload ref: {e}", None
            return
    if has_video_input:
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

    progress(0.40, desc="入队 ComfyUI...")
    yield "⏳ [4/5] queuing prompt to ComfyUI...", None
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
    progress(0.45, desc="等待 ComfyUI 执行...")
    yield "⏳ [5/5] waiting for ComfyUI execution...", None
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
            progress(_wait_p, desc=status_msg.lstrip("⏳✅❌⏰ ").strip()[:40] or "执行中...")
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
    yield "[READY] preparing image gen...", None

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



def _format_elapsed(seconds):
    """把秒数格式化成 mm:ss, 例如 75 -> '01:15'。review P2 让用户感知运行已耗时。"""
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def _now_ts():
    """返回当前时间戳 (秒), 给 status_bar 算已耗时。"""
    import time
    return time.monotonic()


def _render_status_html(state, msg, elapsed_str='', progress_str=''):
    """生成 run-status-bar 的 HTML 内容,根据运行状态切视觉。

    state ∈ {idle, running, success, failure, timeout}: 决定颜色 + 图标。
    elapsed_str: 已耗时字符串(例如 '00:42'),只在 running 时显示。
    progress_str: step 百分比字符串(例如 '60%'),P0/P2/P3 接真实 step 后才有值;
        空串/不传 -> 不渲染胶囊(向后兼容锁, 现有调用方不传)。
    review P2 副标题 2: 让'运行中'成为全局主状态, 状态感更强。
    review 2026-07-17 进度显示: progress_str 让状态条跟 gr.Progress 同步显示真实百分比。
    """
    icons = {'idle': chr(0x23F8), 'running': chr(0x1F504), 'success': chr(0x2705), 'failure': chr(0x274C), 'timeout': chr(0x23F0)}
    state_cn = {'idle': '等待运行', 'running': '正在运行', 'success': '已完成', 'failure': '运行失败', 'timeout': '运行超时'}
    icon = icons.get(state, '•')
    label = state_cn.get(state, state)
    if msg:
        for prefix in (chr(0x23F3), chr(0x2705), chr(0x274C), chr(0x23F0)):
            if msg.startswith(prefix):
                msg = msg[len(prefix):].strip()
                break
        if len(msg) > 60:
            msg = msg[:60] + chr(0x2026)
    elapsed_html = ('<span class="run-status-elapsed">' + chr(0x23F1) + ' ' + elapsed_str + '</span>') if elapsed_str else ''
    # progress 胶囊: 有真实 step 百分比时渲染, 否则不渲染 (单行 flex 最右侧)
    progress_html = ('<span class="run-status-progress">' + (progress_str or '') + '</span>') if progress_str else ''
    # review P3-9: insert ' · ' between state label and msg; otherwise rendered text
    # reads 'waiting to run click below button to start' with no internal punctuation.
    sep = ' · ' if (msg or '').strip() else ''
    return (
        '<div class="run-status-bar run-status-' + state + '">'
        + '<span class="run-status-icon">' + icon + '</span>'
        + '<span class="run-status-label">' + label + '</span>'
        + '<span class="run-status-sep">' + sep + '</span>'
        + '<span class="run-status-msg">' + (msg or '') + '</span>'
        + elapsed_html
        + progress_html
        + '</div>'
    )


def _media_ext_from_url(src):
    """从 URL / 路径里取文件扩展名 (含 query 参数里的 filename).
    ComfyUI /view URL 结构: /view?filename=NAME&type=output&subfolder=SUBFOLDER
    直接 endswith 在 src 上不工作 (URL 后面跟 &type=...&subfolder=...), 需解析
    query 取 filename 的扩展名. 其它 HTTP URL (http://x/clip.mp4) 走 path
    的扩展名; 本地路径走 Path.suffix.
    返回小写扩展名, e.g. ".mp4" / ".png" / "" (无法识别).
    """
    from urllib.parse import urlparse, parse_qs, unquote
    from pathlib import PurePosixPath
    if not src or not isinstance(src, str):
        return ""
    # 本地路径: 走 Path.suffix
    if not src.startswith("http"):
        from pathlib import Path as _P
        return _P(src).suffix.lower()
    # HTTP URL: 优先 path 扩展名; 若是裸端点 (如 /view), 退回 query param 里的 filename
    try:
        parsed = urlparse(src)
    except Exception:
        return ""
    path_ext = PurePosixPath(parsed.path).suffix.lower()
    if path_ext:
        return path_ext
    # query 里找 filename-like value, 按常见 key 顺序: filename (ComfyUI), f (测试用), name, file
    qs = parse_qs(parsed.query, keep_blank_values=False)
    for key in ("filename", "f", "name", "file"):
        for v in qs.get(key, []):
            ext = PurePosixPath(unquote(v)).suffix.lower()
            if ext:
                return ext
    # 兜底: 找 query 里第一个有扩展名的 value
    for values in qs.values():
        for v in values:
            ext = PurePosixPath(unquote(v)).suffix.lower()
            if ext:
                return ext
    return ""


def _media_to_html(media, output_kind: str = "image") -> str:
    """把 run 函数 yield 的 media 转成 HTML。

    output_kind:
      - "image": image list → <img> 网格; 单 URL → <img>
      - "video": <video> (mp4/mov/webm/gif) / 兜底 file-fallback
      - "audio": <audio controls> (mp3/wav/flac) / 兜底 file-fallback

    实际渲染时按 URL / 本地路径的扩展名分桶(image_ext/video_ext/audio_ext),
    与 output_kind 配合: 例如 audio preset 配 .mp3 URL → 走 audio 分支.
    跨类型错误 (e.g. image preset 但 URL 是 .mp3) 也仍能渲染, 不死锁.

    未知 URL / 本地文件 (扩展名不在三个白名单) → 出现路径+下载链接 banner,
    让用户知道文件已生成、可以去下载 — 这是"未知输出类型"的最小可用 fallback.

    直接用 ComfyUI /view URL (浏览器同机可访问), 绕过 gr.Video/gr.Audio 不支持外部 URL 的限制.
    """
    if not media:
        return "<div style=\"color:var(--text-faint);padding:20px\">等待结果...</div>"

    # image 类特化: list → 网格
    if output_kind == "image":
        if isinstance(media, list):
            if not media:
                return "<div style=\"color:var(--text-faint);padding:20px\">等待结果...</div>"
            imgs = "".join(
                "<img src=\"" + str(u) + "\" style=\"max-width:32%;margin:4px;border:1px solid #2a2d33;border-radius:var(--radius-md)\"/>"
                for u in media if u
            )
            return "<div style=\"padding:8px\">" + imgs + "</div>"
        return "<div style=\"padding:8px\"><img src=\"" + str(media) + "\" style=\"max-width:100%;border-radius:var(--radius-md)\"/></div>"

    # video / audio: 单 URL, 扩展名分桶
    src = media[0] if isinstance(media, list) else media
    if not src or not isinstance(src, str):
        return "<div style=\"color:var(--text-faint);padding:20px\">等待结果...</div>"

    ext = _media_ext_from_url(src)
    video_ext = (".mp4", ".mov", ".webm", ".gif")
    image_ext = (".png", ".jpg", ".jpeg", ".webp")
    audio_ext = (".mp3", ".wav", ".flac", ".ogg", ".m4a")

    def _to_url(s):
        """把 http(s) URL 或本地绝对路径转成 gr.Audio / gr.Video 可吃的 URL."""
        if s.startswith("http"):
            return s
        from pathlib import Path as _P
        sp = _P(s)
        if sp.exists():
            try:
                rel = sp.relative_to(config.REPO_ROOT)
                return _FILE_ROUTE_PREFIX + str(rel).replace(chr(92), "/")
            except ValueError:
                return None
        return None

    # 扩展名优先; output_kind 是 hint, 不是 hard constraint
    if ext in audio_ext:
        url = _to_url(src)
        if url:
            return ('<div style=\"padding:8px\"><audio controls preload="metadata" style=\"width:100%;max-width:480px\">'
                    '<source src=\"' + url + '\"/></audio></div>')
    if ext in video_ext:
        if src.startswith("http"):
            return ("<div style=\"padding:8px\"><video controls autoplay style=\"max-width:100%;border-radius:var(--radius-md)\">"
                    "<source src=\"" + src + "\"/></video></div>")
        from pathlib import Path as _P
        sp = _P(src)
        if sp.exists():
            try:
                rel = sp.relative_to(config.REPO_ROOT)
                file_url = _FILE_ROUTE_PREFIX + str(rel).replace(chr(92), "/")
                return ("<div style=\"padding:8px\"><video controls style=\"max-width:100%;border-radius:var(--radius-md)\">"
                        "<source src=\"" + file_url + "\"/></video></div>")
            except ValueError:
                pass
    if ext in image_ext:
        url = _to_url(src) or src
        return "<div style=\"padding:8px\"><img src=\"" + url + "\" style=\"max-width:100%;border-radius:var(--radius-md)\"/></div>"

    # 兜底: 输出 kind 对应的 banner
    if output_kind == "audio":
        url = _to_url(src)
        if url:
            return ('<div class=\"file-fallback\">🎵 <b>音频</b> 已生成: '
                    '<a href=\"' + url + '\" download>下载播放</a> '
                    '<audio controls preload="metadata" style=\"vertical-align:middle;margin-left:8px\">'
                    '<source src=\"' + url + '\"/></audio></div>')
    if output_kind == "video":
        url = _to_url(src)
        if url:
            return ('<div class=\"file-fallback\">🎬 <b>视频</b> 已生成: '
                    '<a href=\"' + url + '\" download>下载</a></div>')
    return ("<div class=\"file-fallback\">📄 未知输出格式: <code>" + src[:80] + "</code></div>")


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

# Gradio 6 文件路由: 所有静态文件通过 /gradio_api/file=<relative path> 提供,
# 不是 /file=<...>。 相对路径在服务端用 os.path.abspath() 解析 (相对 CWD),
# start_webui.bat 会 cd 到项目根, 所以分发到任意路径都仍然正确解析。
# 旧代码用 "/file=" 是错的: Gradio 6 那个路径 404, 浏览器看到的是破图标。
_FILE_ROUTE_PREFIX = "/gradio_api/file="


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
        try:
            for status_msg, media_html, err_upd, re_run_upd, open_dir_upd, last_media in _yield_run_stream(
                run_fn=run_fn,
                preset_name=preset_name,
                vals=vals,
                output_kind=output_kind,
                on_status_done=_on_done,
            ):
                log_text = status_msg
                # P2: 根据 status_msg 前缀切换状态条 (✅→success, ❌/⏰→failure/timeout, 其它→running)
                _state = 'running'
                if status_msg.startswith(chr(0x2705)):
                    _state = 'success'
                elif status_msg.startswith(chr(0x274C)):
                    _state = 'failure'
                elif status_msg.startswith(chr(0x23F0)):
                    _state = 'timeout'
                _elapsed = _format_elapsed(_now_ts() - _run_start_ts)
                # P2: 有 step 时算百分比喂状态条胶囊 (跟 gr.Progress 同源), 无则空串不渲染
                _step = _extract_step_progress(status_msg)
                _pct = (f"{int(_step[0] / _step[1] * 100)}%") if _step is not None else ''
                _status_bar_update = gr.update(value=_render_status_html(_state, status_msg, _elapsed, _pct))
                yield (
                    status_msg,
                    media_html,
                    err_upd,
                    re_run_upd,
                    open_dir_upd,
                    _RUN_BTN_RUNNING,
                    _status_bar_update,
                )
        finally:
            run_btn.interactive = True

        # P2: 根据最后 status_msg 决定状态条终态
        _final_state = 'idle'
        if log_text.startswith(chr(0x2705)):
            _final_state = 'success'
        elif log_text.startswith(chr(0x274C)):
            _final_state = 'failure'
        elif log_text.startswith(chr(0x23F0)):
            _final_state = 'timeout'
        elif log_text:
            # 跑完但 log_text 末尾没有特殊前缀 (异常退出), 仍归 success 让按钮可见
            _final_state = 'success'
        _final_elapsed = _format_elapsed(_now_ts() - _run_start_ts)
        _final_status_bar = gr.update(value=_render_status_html(_final_state, log_text, _final_elapsed if _final_state == 'running' else ''))
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

_TOKENS_CACHE: str | None = None
_THEMES_CACHE: list[dict] | None = None
_DEFAULT_THEME_ID = "coral-orange"  # fallback only —— actual startup value comes from _resolve_initial_theme()
_THEMES_PATH = config.REPO_ROOT / "app" / "presets" / "themes.json"
_TOKENS_PATH = config.REPO_ROOT / "app" / "static" / "tokens.css"



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


def _load_saved_theme() -> str:
    """启动时读取 config.THEME_SETTINGS_FILE 取上次选的主题。

    文件不存在 / 解析失败 / theme id 不在 themes.json 里 → 回退 _DEFAULT_THEME_ID(coral-orange)。
    失败永不让 UI 崩,最多回到默认。
    """
    try:
        import json
        data = json.loads(config.THEME_SETTINGS_FILE.read_text(encoding="utf-8"))
        tid = data.get("theme_id")
        if tid and tid in {t["id"] for t in _list_themes()}:
            return tid
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return _DEFAULT_THEME_ID


def _save_theme(theme_id: str) -> None:
    """用户切换主题时把 theme_id 写到 config.THEME_SETTINGS_FILE 持久化。

    写盘失败(e.g. 权限)只静默 —— UI 已经看到新主题,持久化失败下次启动会回到默认。
    """
    try:
        import json
        config.THEME_SETTINGS_FILE.write_text(
            json.dumps({"theme_id": theme_id}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass

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
    """组装 launch(css=...) 的入参。包含 tokens.css 全文 + 默认主题。

    返回**单个 CSS 字符串**(Gradio 6 的 launch(css=...) 签名是 str | None,
    不是 list)。Gradio 内部会用 CSSStyleSheet.replaceSync 解析这个字符串,
    再自己包 <style>; 必须是纯 CSS(不带 <style> 标签),且必须是 str 不是 list —
    早期版本误传 list[str] 导致 replaceSync 收到 object → 前端
    "e.replace is not a function" → 页面永远卡在"加载中"。

    默认 mode 是 "auto"(由浏览器 media query 决定),所以默认模式下
    surface override 是空的,不会跟 @media 块冲突。
    """
    tokens = _load_tokens_css()
    default_combined = _apply_theme(_load_saved_theme())
    # _apply_theme 返回 "<style>:root{...}</style>",剥掉 <style></style> 标签
    default_css = _strip_style_tag(default_combined)
    # Gradio 6.20.0 workaround: advanced accordion 里的 status-tracker 永远不消失,
    # 遮住真实组件 (gr.Number / gr.Slider 都有这个 bug)。强制隐藏 .custom-accordion
    # 里的 status-tracker, 让 Number 输入框 + 最小/最大值显示能看见。运行进度仍
    # 由 运行日志 文本框显示, 不影响用户感知。
    accordion_status_tracker_fix = "/* Gradio 6.20.0 workaround: hide stuck status-tracker in accordions */ .custom-accordion [data-testid='status-tracker'] { display: none !important; }"
    # 合并成单个字符串(Gradio 6 不接受 list)
    return f"{tokens}\n{default_css}\n{accordion_status_tracker_fix}"


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
        footer_links=[],
        enable_monitoring=False,
        allowed_paths=[config.REPO_ROOT / "app" / "static" / "examples"],
    )


if __name__ == "__main__":
    main()