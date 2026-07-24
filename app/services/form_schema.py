"""表单 schema + 校验 + 文件解析 — preset spec ↔ 表单值映射.

公开符号:
  - get_video_frames / estimated_segments   段数预估
  - validate_inputs                         文件大小/扩展名校验
  - parse_sizes                             "720x1280" → (w, h)
  - example_to_form_values                  preset.example → 表单值列表
  - _manifest_to_form_values                历史 manifest → 表单值列表
  - _resolve_example_file                   example 文件名 → ComfyUI input 纯文件名
  - _resolve_upload_name / _is_comfy_input_file  上传去重

依赖:
  - app.config (COMFY_INPUT_DIR / REPO_ROOT / ALLOWED_*_EXT / MAX_*_MB)
  - app.scail2_client.upload
"""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

from app import config
from app import scail2_client

_SIZE_PAT = re.compile(r"(\d+)\s*[x×]\s*(\d+)")


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
      不再靠 node_id 隐式兜底。

    文件槽位返回 ComfyUI input 目录下的**纯文件名** (basename). 前端通过
    /comfy_input/<name> 路由展示缩略图; 运行时 _resolve_upload_name 识别它在
    COMFY_INPUT_DIR 跳过重复上传. 找不到文件时返 None (前端显示空缩略图, 用户手动上传).
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
            # 跟 example_to_form_values 对称: 用 spec.example_key 从 manifest 取值
            example_key = spec.get("example_key", spec.get("field", ""))
            v = manifest.get(example_key)
            if v is None and example_key in ("main_prompt", "prompt"):
                v = manifest.get("prompt_text")
            if v is None:
                v = spec.get("default")
            values.append(v)
    return values


def _resolve_example_file(filename):
    """把 example 里的文件名解析成前端能展示、runner 能上传的值。

    Flask 版: 直接返回 ComfyUI input 目录下的文件**纯文件名** (basename).
    - 前端通过 /comfy_input/<filename> 路由展示缩略图 (flask_app.comfy_input)
    - runner 上传时 _resolve_upload_name 识别它在 ComfyUI input 目录, 跳过重复上传

    返回 None 的情况 (让前端显示空缩略图, 用户自己上传):
      - filename 为空
      - 文件在 COMFY_INPUT_DIR 找不到 (也没在绝对路径找到)

    历史 (Gradio 6 时代): 曾把文件复制到 .examples_cache/ 绕过 gr.File 的安全限制,
    Gradio 下线后这个 workaround 不需要了 (migrate-to-flask 清理 2026-07-24).
    """
    if not filename:
        return None
    # 找源文件: 先按绝对路径, 再拼 COMFY_INPUT_DIR
    src = Path(filename)
    if not src.is_absolute():
        src = config.COMFY_INPUT_DIR / filename
    if not src.exists():
        # 也可能在 CWD 下 (历史 staged 路径)
        src = Path(filename)
        if not src.exists():
            return None
    return src.name


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
