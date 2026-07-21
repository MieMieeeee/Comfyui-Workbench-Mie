"""Flask app — ComfyUI Web Workflow Runner 的 Flask 版本.

步骤 2 (本次): 非流式路由. SSE 流式 /api/run/<preset> 在步骤 4.
文件上传 /api/upload 在步骤 5.

业务逻辑全部走 app.services.* + app.scail2_client / history / health_check,
跟 Gradio 版共享同一套纯函数.

启动: python -m app.flask_app  (端口 8199, 同 Gradio 版)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# bootstrap (跟 scail2_app.py 一致): 让 `python -m app.flask_app` 能跑
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from flask import Flask, jsonify, request, Response, render_template

from app import config
from app import scail2_client
from app import prompts as prompts_mod
from app.services import theme
from app.services import form_schema
from app.services import runner
from app.services.persistence import _save_last_run, _load_last_run


# ============================================================
# Flask app 构造
# ============================================================

app = Flask(
    __name__,
    template_folder=str(_REPO_ROOT / "app" / "templates"),
    static_folder=str(_REPO_ROOT / "app" / "static"),
    static_url_path="/static",
)
app.config["JSON_AS_ASCII"] = False  # 中文响应不转义


# ============================================================
# 业务逻辑 helper (从 scail2_app.py 复制/改编, 不依赖 Gradio)
# ============================================================

def _save_url_action(url: str) -> str:
    """保存 URL + 测试连通性, 返回状态消息. 复用 scail2_app.save_and_test_url 逻辑."""
    cleaned = scail2_client.set_base_url(url)
    if not cleaned:
        return "⚠️ URL 为空，请填写 ComfyUI 地址"
    _ok, msg = scail2_client.check_connection(url=cleaned, timeout=5)
    return msg


def _reset_url_action():
    """恢复默认 URL. 返回 (default_url, message)."""
    scail2_client.reset_base_url()
    default = config.COMFY_BASE_URL
    _ok, msg = scail2_client.check_connection(url=default, timeout=5)
    return default, msg


def _comfy_status_dict() -> dict:
    """连接状态 {ok, url, dot}. 复用 scail2_app._comfy_status_text 逻辑."""
    try:
        ok, _msg = scail2_client.check_connection(timeout=2)
    except Exception:
        ok = False
    return {
        "ok": bool(ok),
        "url": scail2_client.get_base_url(),
        "dot": "🟢" if ok else "🔴",
    }


def _full_health_markdown() -> str:
    from app import health_check
    return health_check.check_health(timeout=8).to_markdown()


def _update_est_markdown(drive_path, per_seg=81, pre_drop=5, max_segments=0) -> str:
    """复用 scail2_app._update_est 逻辑."""
    if not drive_path:
        return "**预估段数**: 上传驱动视频后显示"
    frames = form_schema.get_video_frames(drive_path)
    if frames is None:
        return f"**预估段数**: 读取帧数失败 ({drive_path})"
    from app.services.form_schema import estimated_segments
    auto = estimated_segments(frames, per_seg, pre_drop, max_segments=0)
    est = estimated_segments(frames, per_seg, pre_drop, max_segments=max_segments)
    net = max(1, int(per_seg) - int(pre_drop))
    if max_segments and max_segments > 0:
        if est < auto:
            return f"**预估段数**: {est} (已限制)  \n(驱动视频 {frames} 帧 / 每段 {per_seg} / pre-drop {pre_drop} / 净每段 {net} / 限制 ≤ {max_segments}, 自动算 {auto})"
        else:
            return f"**预估段数**: {est}  \n(驱动视频 {frames} 帧 / 每段 {per_seg} / pre-drop {pre_drop} / 净每段 {net} / 限制 ≤ {max_segments})"
    return f"**预估段数**: {est} (无限制)  \n(驱动视频 {frames} 帧 / 每段 {per_seg} / pre-drop {pre_drop} / 净每段 {net})"


def _open_output_dir() -> str:
    """打开 ComfyUI 输出目录 (服务端调用, 仅本地部署有效)."""
    import platform
    import subprocess
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


def _category_icon(cat: str) -> str:
    return {
        "video": "🎬", "image": "🖼️", "audio": "🔊",
        "3d": "🧊", "other": "📦",
    }.get(cat, "📦")


# ============================================================
# 页面路由
# ============================================================

def _workflows_for_nav():
    """返回前端 nav 用的工作流元信息列表 (跟 /api/workflows 一致)."""
    out = []
    for w in config.list_workflows():
        cfg = config.preset_config(w["name"])
        cat = cfg.get("category", "other")
        out.append({
            "name": w["name"],
            "display_name": cfg.get("display_name", w["name"]),
            "description": cfg.get("description", ""),
            "category": cat,
            "icon": _category_icon(cat),
            "nav_label": f"{_category_icon(cat)} {cfg.get('display_name', w['name'])}",
            "output_kind": cfg.get("output_kind") or (
                "image" if cat == "image" else "audio" if cat == "audio" else "video"
            ),
        })
    return out


@app.route("/")
def index():
    """运行页."""
    tid = theme._load_saved_theme()
    # 每个 preset 的 cfg 也在服务端预渲染, 前端不用 fetch /api/preset_cfg/<name>
    preset_cfgs = {}
    for w in config.list_workflows():
        cfg = config.preset_config(w["name"])
        preset_cfgs[w["name"]] = {
            "name": w["name"],
            "display_name": cfg.get("display_name", w["name"]),
            "description": cfg.get("description", ""),
            "category": cfg.get("category", "other"),
            "output_kind": cfg.get("output_kind") or (
                "image" if cfg.get("category") == "image"
                else "audio" if cfg.get("category") == "audio" else "video"
            ),
            "user_facing_inputs": cfg.get("user_facing_inputs", []),
        }
    return render_template(
        "run.html",
        workflows=_workflows_for_nav(),
        preset_cfgs=preset_cfgs,
        theme_css_content=theme._strip_style_tag(theme._apply_theme(tid)),
        page_bg_color=theme._PAGE_BG_COLOR,
    )


@app.route("/settings")
def settings_page():
    """设置页."""
    tid = theme._load_saved_theme()
    return render_template(
        "settings.html",
        default_url=config.COMFY_BASE_URL,
        current_url=scail2_client.get_base_url(),
        theme_css_content=theme._strip_style_tag(theme._apply_theme(tid)),
        page_bg_color=theme._PAGE_BG_COLOR,
    )


# ============================================================
# API 路由 — 主题
# ============================================================

@app.route("/api/themes")
def get_themes():
    """所有主题列表."""
    return jsonify([
        {"id": t["id"], "name": t["name"], "desc": t["desc"]}
        for t in theme._list_themes()
    ])


@app.route("/api/theme")
def get_current_theme():
    """当前主题 (id + css + desc)."""
    tid = theme._load_saved_theme()
    return jsonify({
        "theme_id": tid,
        "css": theme._apply_theme(tid),
        "desc": theme._get_theme_desc(tid),
    })


@app.route("/api/theme", methods=["POST"])
def set_theme():
    """切换主题. body: {"theme_id": "..."}."""
    data = request.get_json(silent=True) or {}
    tid = data.get("theme_id")
    if not tid or tid not in {t["id"] for t in theme._list_themes()}:
        return jsonify({"error": f"unknown theme_id: {tid}"}), 400
    theme._save_theme(tid)
    return jsonify({
        "theme_id": tid,
        "css": theme._apply_theme(tid),
        "desc": theme._get_theme_desc(tid),
    })


# ============================================================
# API 路由 — 示例 / 上次参数
# ============================================================

@app.route("/api/example/<preset_name>")
def get_example(preset_name):
    """加载示例素材 (按 user_facing_inputs 顺序的值列表)."""
    valid = {w["name"] for w in config.list_workflows()}
    if preset_name not in valid:
        return jsonify({"error": f"unknown preset: {preset_name}"}), 404
    return jsonify(form_schema.example_to_form_values(preset_name))


@app.route("/api/last_run/<preset_name>")
def get_last_run(preset_name):
    """加载上次成功参数. 没跑过返全 None 列表."""
    cfg = config.preset_config(preset_name)
    n = sum(2 if s.get("type") == "int_random" else 1 for s in cfg["user_facing_inputs"])
    return jsonify(_load_last_run(preset_name, n))


# ============================================================
# API 路由 — ComfyUI 连接 / 设置
# ============================================================

@app.route("/api/comfy_status")
def comfy_status():
    return jsonify(_comfy_status_dict())


@app.route("/api/settings/url", methods=["POST"])
def save_url():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    return jsonify({"message": _save_url_action(url)})


@app.route("/api/settings/url/reset", methods=["POST"])
def reset_url():
    default, msg = _reset_url_action()
    return jsonify({"url": default, "message": msg})


@app.route("/api/settings/url/test")
def test_url():
    _ok, msg = scail2_client.check_connection(timeout=5)
    return jsonify({"message": msg})


@app.route("/api/health")
def health():
    return jsonify({"report": _full_health_markdown()})


# ============================================================
# API 路由 — 随机提示词 / 段数预估
# ============================================================

@app.route("/api/random_prompt")
def random_prompt():
    n = request.args.get("n", default=1, type=int)
    if n <= 1:
        return jsonify({"prompt": prompts_mod.random_prompt()})
    return jsonify({"prompt": "\n---\n".join(prompts_mod.random_prompts(n=n))})


@app.route("/api/estimated_segments")
def estimated_segments_route():
    drive_path = request.args.get("drive_path", "")
    per_seg = request.args.get("per_seg", default=81, type=int)
    pre_drop = request.args.get("pre_drop", default=5, type=int)
    max_segments = request.args.get("max_segments", default=0, type=int)
    return jsonify({
        "markdown": _update_est_markdown(drive_path, per_seg, pre_drop, max_segments),
    })


# ============================================================
# API 路由 — 打开输出目录
# ============================================================

@app.route("/api/open_output_dir", methods=["POST"])
def open_output_dir():
    return jsonify({"message": _open_output_dir()})


# ============================================================
# API 路由 — 工作流列表 (前端 nav 用)
# ============================================================

@app.route("/api/workflows")
def workflows():
    out = []
    for w in config.list_workflows():
        cfg = config.preset_config(w["name"])
        cat = cfg.get("category", "other")
        out.append({
            "name": w["name"],
            "display_name": cfg.get("display_name", w["name"]),
            "description": cfg.get("description", ""),
            "category": cat,
            "icon": _category_icon(cat),
            "nav_label": f"{_category_icon(cat)} {cfg.get('display_name', w['name'])}",
            "output_kind": cfg.get("output_kind") or (
                "image" if cat == "image" else "audio" if cat == "audio" else "video"
            ),
        })
    return jsonify(out)


# ============================================================
# API 路由 — SSE 流式运行 (步骤 4)
# ============================================================

@app.route("/api/run/<preset_name>", methods=["POST"])
def run_preset(preset_name):
    """流式运行 preset. POST body: {"form_values": [...]}.
    返回 text/event-stream, 每个 RunEvent 一个 'data:' 行, 末尾 [DONE].
    """
    valid = {w["name"] for w in config.list_workflows()}
    if preset_name not in valid:
        return jsonify({"error": f"unknown preset: {preset_name}"}), 404

    data = request.get_json(silent=True) or {}
    form_values = data.get("form_values", [])
    if not isinstance(form_values, list):
        return jsonify({"error": "form_values must be a list"}), 400

    # 成功时持久化 last_run
    def on_success(name, vals):
        _save_last_run(name, vals)

    def event_stream():
        try:
            for ev in runner.stream_events(preset_name, form_values, on_success=on_success):
                yield ev.to_sse()
        except Exception as e:
            # 兜底: 生成器内部异常, 发一个 error event
            import json as _json
            err_data = {
                "type": "error",
                "error_html": f"<div class='error-banner-inner'><b>服务器异常</b><br>{e}</div>",
                "state": "failure",
            }
            yield f"data: {_json.dumps(err_data, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 不缓冲
        },
    )


# ============================================================
# API 路由 — 文件上传 (步骤 5)
# ============================================================

@app.route("/api/upload", methods=["POST"])
def upload_file():
    """上传文件到 ComfyUI input 目录.

    multipart form: file=<文件>
    返回 {"name": "<ComfyUI 端文件名>", "subfolder": "...", "type": "input"}.
    前端把 name 存进 formValues, run_workflow 的 _resolve_upload_name 会识别
    它已在 ComfyUI input 目录, 跳过重复上传.
    """
    if "file" not in request.files:
        return jsonify({"error": "missing 'file' in form data"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "empty filename"}), 400

    # 校验扩展名 (按 kind 参数, 默认 image)
    kind = request.form.get("kind", "image")
    from pathlib import Path as _P
    ext = _P(f.filename).suffix.lower()
    allowed = config.ALLOWED_IMAGE_EXT if kind == "image" else config.ALLOWED_VIDEO_EXT
    if ext not in allowed:
        return jsonify({
            "error": f"extension {ext} not allowed (allowed: {sorted(allowed)})",
        }), 400

    # 校验大小
    f.stream.seek(0, 2)
    size = f.stream.tell()
    f.stream.seek(0)
    size_mb = size / (1024 * 1024)
    max_mb = config.MAX_IMAGE_MB if kind == "image" else config.MAX_VIDEO_MB
    if size_mb > max_mb:
        return jsonify({
            "error": f"file too large: {size_mb:.1f}MB > {max_mb}MB",
        }), 400

    # 保存到临时目录, 调 scail2_client.upload 上传到 ComfyUI
    import tempfile
    import os as _os
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(f.filename) or "upload.bin"
    tmp_path = _P(tempfile.gettempdir()) / safe_name
    f.save(str(tmp_path))
    try:
        result = scail2_client.upload(str(tmp_path), kind=kind)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    return jsonify(result)


@app.route("/api/preset_cfg/<preset_name>")
def preset_cfg(preset_name):
    """返回 preset 的 user_facing_inputs spec 列表, 供前端动态渲染表单字段."""
    valid = {w["name"] for w in config.list_workflows()}
    if preset_name not in valid:
        return jsonify({"error": f"unknown preset: {preset_name}"}), 404
    cfg = config.preset_config(preset_name)
    # 只返回前端需要的字段 (不泄露 fixed_patches / do_not_modify_warnings 等)
    return jsonify({
        "name": preset_name,
        "display_name": cfg.get("display_name", preset_name),
        "description": cfg.get("description", ""),
        "category": cfg.get("category", "other"),
        "output_kind": cfg.get("output_kind") or (
            "image" if cfg.get("category") == "image"
            else "audio" if cfg.get("category") == "audio" else "video"
        ),
        "user_facing_inputs": cfg.get("user_facing_inputs", []),
    })


# ============================================================
# 启动入口 (步骤 6 完整接管)
# ============================================================

def main():
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "8199"))
    print(f"Flask WebUI: http://{host}:{port}")
    # threaded=True 让 SSE 不阻塞其他请求
    app.run(host=host, port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
