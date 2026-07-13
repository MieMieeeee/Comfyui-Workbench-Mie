"""ComfyUI HTTP 客户端 — 唯一跟 ComfyUI 8188 直接打交道的模块。

约定：
- 所有路径/端口/阈值从 app.config 读，不写死
- 所有 workflow 加载/校验走 validate，不假设结构
- 所有错误分类：ValidationError / ConnectionError / ExecutionError

端点注意：当前 ComfyUI 0.24 只有 POST /upload/image 端点（接受任意文件类型，
不只是 image）。ARCHITECTURE.md 之前写的 /upload/file 端点不存在（返 405）。
"""
from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

import requests

from . import config
from .workflow_validator import validate, WorkflowValidationError


# --- 自定义异常（阶段 4 会用，先定义好） ---

class ComfyUIError(Exception):
    """所有 ComfyUI 相关错误的基类。"""


class ConnectionError_(ComfyUIError):
    """ComfyUI 8188 连不上 / 超时。"""


class ProtocolError_(ComfyUIError):
    """HTTP 状态码非 2xx / 响应不是 JSON / 字段缺失。"""


class ExecutionError_(ComfyUIError):
    """ComfyUI 接受 prompt 但 status.status_str != 'success'。"""


# --- 运行时可变的 ComfyUI base URL ---
#
# 默认从 config.COMFY_BASE_URL 读（环境变量覆盖），但允许 UI 运行时修改
# （设置页）。所有 HTTP 调用都走 get_base_url()，不直接读 config.COMFY_BASE_URL。
_runtime_base_url: str = config.COMFY_BASE_URL


def get_base_url() -> str:
    """当前生效的 ComfyUI base URL（运行时可被 set_base_url 改）。"""
    return _runtime_base_url


def set_base_url(url: str) -> str:
    """设置运行时 base URL，规范化（去尾斜杠 + strip），返回规范化后的值。"""
    global _runtime_base_url
    cleaned = (url or "").strip().rstrip("/")
    _runtime_base_url = cleaned
    return cleaned


def reset_base_url() -> None:
    """重置到 config 里的默认值（主要用于测试 + UI 的"恢复默认"）。"""
    global _runtime_base_url
    _runtime_base_url = config.COMFY_BASE_URL


def check_connection(url: str | None = None, timeout: int = 5) -> tuple[bool, str]:
    """检查 ComfyUI 是否可达（轻量 L0 探针）。

    url=None 时用当前运行时 base url；指定 url 时只测试该地址（不改全局状态）。
    返回 (ok, message)。ok=True 时 message 是成功信息；False 时是可操作的诊断建议。
    不抛异常。

    失败时会区分原因（端口没监听/超时/主机不可达）并给出操作建议，
    而不是笼统的"无法连接"。深度检查（模型/节点）用 health_check.check_health。
    """
    from .health_check import _diagnose_connection_error
    target = url or _runtime_base_url
    target = (target or "").strip().rstrip("/")
    if not target:
        return False, "URL 为空"
    try:
        resp = requests.get(f"{target}/system_stats", timeout=timeout)
        if resp.status_code == 200:
            return True, f"✅ ComfyUI 就绪: {target}"
        return False, f"ComfyUI 返回 HTTP {resp.status_code}，`{target}` 可能不是 ComfyUI 实例"
    except requests.ConnectionError as e:
        return False, _diagnose_connection_error(target, e)
    except requests.Timeout:
        return False, f"⏰ 连接超时（{timeout}s）。地址 `{target}` 可能错误或被防火墙拦截。"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# --- workflow 加载 / patch / validate ---

def load_workflow_template(preset_name: str) -> dict[str, Any]:
    """从 app/presets/{name}.json 加载 workflow 模板。

    返回的 dict 顶层是 node_id (str) → node 配置。这是 ComfyUI API 格式。
    """
    path = config.workflow_path(preset_name)
    if not path.exists():
        raise FileNotFoundError(f"workflow template not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def patch_workflow(
    workflow: dict[str, Any],
    replacements: dict[str, dict[str, Any]],
    preset_config: dict[str, Any] | None = None,
    *,
    validate_after: bool = True,
) -> dict[str, Any]:
    """按 replacements 替换 workflow 里指定 node 的 inputs 字段。

    replacements 格式：
        {"30": {"image": "foo.png"}, "479": {"int_range_end": 8}}

    如果传 preset_config 且 validate_after=True，patch 完跑一次 validate。
    """
    # 深拷贝每个 node 的 inputs（顶层 dict(v) 不够：node["inputs"] 还是引用，
    # 直接改会污染原 workflow）。只深拷贝 inputs 即可，其它字段（class_type/_meta）不可变。
    patched: dict[str, Any] = {}
    for k, v in workflow.items():
        node_copy = dict(v)
        if isinstance(node_copy.get("inputs"), dict):
            node_copy["inputs"] = dict(node_copy["inputs"])
        patched[k] = node_copy
    for node_id, fields in replacements.items():
        if node_id not in patched:
            raise WorkflowValidationError(
                f"patch_workflow: target node {node_id} not in workflow"
            )
        node = patched[node_id]
        if "inputs" not in node or not isinstance(node["inputs"], dict):
            node["inputs"] = {}
        for field, value in fields.items():
            node["inputs"][field] = value

    if validate_after and preset_config is not None:
        validate(patched, preset_config)
    return patched


# --- HTTP 动作 ---

# 当前 ComfyUI 0.24 只有这一个 upload 端点（接受任意文件类型）。
# form 字段名固定用 "image"，但 body 字节可以是 png/mp4/jpg 等任意类型。
UPLOAD_ENDPOINT = "/upload/image"


def upload(file_path: str | Path, kind: str = "image") -> dict[str, str]:
    """上传文件到 ComfyUI input 目录。

    注：当前 ComfyUI 0.24 只有一个 /upload/image 端点，接受任意文件类型。
    `kind` 参数已无实际作用（端点不区分 image/file），保留签名仅为向后兼容。
    将来若 ComfyUI 加 /upload/file 端点，在此分支即可。

    返回：{"name": "...", "subfolder": "...", "type": "input"}
    """
    _ = kind  # 当前 ComfyUI 只有一个 upload 端点，kind 不影响行为
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"upload: file not found: {p}")

    mime, _ = mimetypes.guess_type(str(p))
    mime = mime or "application/octet-stream"

    try:
        with p.open("rb") as f:
            # ComfyUI upload 端点的 form 字段名固定是 "image"（与文件类型无关）
            files = {"image": (p.name, f, mime)}
            data = {"type": "input", "overwrite": "true"}
            resp = requests.post(
                get_base_url() + UPLOAD_ENDPOINT,
                files=files,
                data=data,
                timeout=60,
            )
    except requests.ConnectionError as e:
        raise ConnectionError_(f"cannot connect to {get_base_url()}: {e}") from e
    except requests.Timeout as e:
        raise ConnectionError_(f"upload timeout: {e}") from e

    if resp.status_code != 200:
        raise ProtocolError_(f"upload failed: HTTP {resp.status_code} body={resp.text[:200]}")

    try:
        result = resp.json()
    except json.JSONDecodeError as e:
        raise ProtocolError_(f"upload returned non-JSON: {resp.text[:200]}") from e

    if "name" not in result:
        raise ProtocolError_(f"upload response missing 'name' field: {result}")

    return result


def queue_prompt(
    workflow: dict[str, Any],
    client_id: str | None = None,
) -> str:
    """入队一个 workflow 到 ComfyUI。

    返回 prompt_id（str）。

    注意：workflow 是 node_id → 配置 的 dict，HTTP body 会被包成
    {"prompt": <workflow>, "client_id": <id>}。
    """
    cid = client_id or str(uuid.uuid4())
    body = {"prompt": workflow, "client_id": cid}

    try:
        resp = requests.post(
            get_base_url() + "/prompt",
            json=body,
            timeout=30,
        )
    except requests.ConnectionError as e:
        raise ConnectionError_(f"cannot connect to {get_base_url()}: {e}") from e
    except requests.Timeout as e:
        raise ConnectionError_(f"queue_prompt timeout: {e}") from e

    if resp.status_code != 200:
        # ComfyUI 返 400 时 body 通常是 {"error": "...", "node_errors": {...}}
        try:
            err_body = resp.json()
        except json.JSONDecodeError:
            err_body = {"raw": resp.text[:500]}
        raise ProtocolError_(f"queue_prompt failed: HTTP {resp.status_code} body={err_body}")

    try:
        result = resp.json()
    except json.JSONDecodeError as e:
        raise ProtocolError_(f"queue_prompt returned non-JSON: {resp.text[:200]}") from e

    if "prompt_id" not in result:
        raise ProtocolError_(f"queue_prompt response missing 'prompt_id': {result}")

    return result["prompt_id"]


def get_history(prompt_id: str) -> dict[str, Any] | None:
    """查 /history/{prompt_id}。

    返回 history dict（顶层 key 是 prompt_id），或 None（如果还没记录）。
    """
    try:
        resp = requests.get(
            f"{get_base_url()}/history/{prompt_id}",
            timeout=15,
        )
    except requests.ConnectionError as e:
        raise ConnectionError_(f"cannot connect to {get_base_url()}: {e}") from e
    except requests.Timeout as e:
        raise ConnectionError_(f"get_history timeout: {e}") from e

    if resp.status_code != 200:
        raise ProtocolError_(f"get_history failed: HTTP {resp.status_code} body={resp.text[:200]}")

    try:
        result = resp.json()
    except json.JSONDecodeError as e:
        raise ProtocolError_(f"get_history returned non-JSON: {resp.text[:200]}") from e

    # 还没开始执行时，ComfyUI 返 {} 或没有这个 key
    if not result or prompt_id not in result:
        return None
    return result[prompt_id]


def extract_primary_video_output(history: dict[str, Any]) -> dict[str, str] | None:
    """从 history.outputs 里抓第一个 video/gif/audio 输出。

    返回 {"filename": ..., "subfolder": ..., "type": "output"} 或 None。
    兼容 video/gif (VHS_VideoCombine, SaveVideo) + audio (SaveAudioMP3, SaveAudio)。
    判定方法: history.outputs[node_id] 里出现 videos/gifs/files/audio 任一 key,
    按 node_id 顺序取第一项。具体是图是视频还是音频由 caller 端 (output_kind) 决定
    该把这个 URL 喂给 gr.Video / gr.Audio / gr.Image 还是 _media_to_html。
    """
    if not history:
        return None
    outputs = history.get("outputs", {})
    if not outputs:
        return None
    # 按 node_id 顺序遍历，优先 videos > gifs > files > audio
    # (audio 放最后是为了避免和某些节点的 files key 冲突,实际不会重叠,顺序无所谓)
    for node_id in sorted(outputs.keys()):
        node_out = outputs[node_id]
        for key in ("videos", "gifs", "files", "audio"):
            items = node_out.get(key, [])
            if items and isinstance(items, list):
                first = items[0]
                if isinstance(first, dict) and "filename" in first:
                    return {
                        "filename": first["filename"],
                        "subfolder": first.get("subfolder", ""),
                        "type": first.get("type", "output"),
                    }
    return None


def extract_all_image_outputs(history: dict[str, Any]) -> list[dict[str, str]]:
    """从 history.outputs 里抓所有 image 输出（多尺寸文生图用）。

    返回 list of {"filename": ..., "subfolder": ..., "type": ...}。
    """
    if not history:
        return []
    outputs = history.get("outputs", {})
    if not outputs:
        return []
    results: list[dict[str, str]] = []
    for node_id in sorted(outputs.keys()):
        node_out = outputs[node_id]
        items = node_out.get("images", [])
        if items and isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and "filename" in item:
                    results.append({
                        "filename": item["filename"],
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    })
    return results


def get_output_url(filename: str, subfolder: str = "", kind: str = "output") -> str:
    """拼 /view URL。gr.Video 直接吃这个 URL。"""
    from urllib.parse import quote
    qs = f"filename={quote(filename)}&type={kind}&subfolder={quote(subfolder)}"
    return f"{get_base_url()}/view?{qs}"


# --- 流式轮询 ---

def wait_for_completion(
    prompt_id: str,
    timeout_sec: int | None = None,
    poll_interval_sec: int | None = None,
) -> Iterator[str]:
    """轮询 /history/{id} 直到 completed 或 timeout。

    yield 状态字符串给 Gradio 流式更新。
    """
    timeout = timeout_sec if timeout_sec is not None else config.DEFAULT_TIMEOUT_SEC
    interval = poll_interval_sec if poll_interval_sec is not None else config.POLL_INTERVAL_SEC
    start = time.time()

    while time.time() - start < timeout:
        try:
            hist = get_history(prompt_id)
        except ConnectionError_ as e:
            yield f"\u274c connection error: {e}"
            return

        if hist is None:
            elapsed = int(time.time() - start)
            yield f"\u23f3 {elapsed // 60:02d}:{elapsed % 60:02d}  waiting for {prompt_id[:8]}\u2026"
            time.sleep(interval)
            continue

        status = hist.get("status", {})
        completed = status.get("completed", False)
        status_str = status.get("status_str", "")
        elapsed = int(time.time() - start)

        if completed:
            if status_str == "success":
                yield f"\u2705 done in {elapsed // 60:02d}:{elapsed % 60:02d}"
            else:
                err = _extract_error_from_status(status)
                yield f"\u274c {status_str}: {err}"
            return

        # 未完成：报最近执行的节点（如果有）
        last_node = _last_executed_node(hist)
        suffix = f"  {last_node}" if last_node else ""
        yield f"\u23f3 {elapsed // 60:02d}:{elapsed % 60:02d}  running\u2026{suffix}"
        time.sleep(interval)

    yield f"\u23f0 timeout after {timeout // 60} min"


def _extract_error_from_status(status: dict[str, Any]) -> str:
    """从 status.messages 数组抽最关键的一条错误。"""
    messages = status.get("messages", [])
    if not messages:
        return "unknown error"
    # 优先找 execution_error 类型
    for msg in messages:
        if isinstance(msg, list) and len(msg) >= 2:
            kind, content = msg[0], msg[1]
            if "error" in str(kind).lower():
                return str(content)[:200]
    # 否则取最后一条
    last = messages[-1]
    if isinstance(last, list) and len(last) >= 2:
        return str(last[1])[:200]
    return str(last)[:200]


def _last_executed_node(history: dict[str, Any]) -> str | None:
    """从 status.messages 找最近执行的节点号（"30" / "479" 等）。"""
    messages = history.get("status", {}).get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, list) and len(msg) >= 2:
            kind, content = msg[0], msg[1]
            if "executing" in str(kind).lower() and isinstance(content, str):
                return f"node {content}"
    return None