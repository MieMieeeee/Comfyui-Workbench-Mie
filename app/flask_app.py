"""Flask app — ComfyUI Web Workflow Runner 的 web 入口.

业务逻辑全部走 app.services.* + app.scail2_client / history / health_check.
路由分两类: 页面 (HTML 渲染) + API (JSON / SSE).

启动: python -m app.flask_app  (端口 8199)
"""
from __future__ import annotations

import json
import os
import sys

import requests
from pathlib import Path

# bootstrap: 让 `python -m app.flask_app` 能跑 (不在仓库根时也 OK)
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from flask import Flask, jsonify, request, Response, render_template, url_for, send_from_directory, stream_with_context

from app import config
from app import scail2_client
from app import prompts as prompts_mod
from app.services import theme
from app.services import form_schema
from app.services import runner
from app.services import wizard
from app.services import workflow_editor
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
# 业务逻辑 helper
# ============================================================

def _save_url_action(url: str) -> str:
    """保存 URL + 测试连通性, 返回状态消息."""
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
    """连接状态 {ok, url, port, dot}.

    review 2026-07-28: 加 port 字段, 顶部菜单栏的状态 pill 要显示 "ComfyUI · 8188" 这种短标签.
    解析失败时 port=None, 客户端会显示 "ComfyUI · ?".
    """
    import re as _re
    url = scail2_client.get_base_url()
    port = None
    m = _re.search(r":(\d+)(?=/|$)", url)
    if m:
        try:
            port = int(m.group(1))
        except (TypeError, ValueError):
            port = None
    try:
        ok, _msg = scail2_client.check_connection(timeout=1)
    except Exception:
        ok = False
    return {
        "ok": bool(ok),
        "url": url,
        "port": port,
        "dot": "🟢" if ok else "🔴",
    }


def _full_health_markdown() -> str:
    from app import health_check
    return health_check.check_health(timeout=8).to_markdown()


def _update_est_markdown(drive_path, per_seg=81, pre_drop=5, max_segments=0) -> str:
    """根据驱动视频帧数预估段数, 返回 markdown 字符串."""
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


# nav 用的 5 个固定组, 跟 wizard 调整顺序 tab 的 _GROUP_ORDER 对齐
# (顺序就是显示顺序, 跟 group field 走)
_NAV_GROUPS = ("图像", "视频", "音频", "通用", "其他")
_NAV_GROUP_BY_CATEGORY = {
    "image": "图像", "video": "视频", "audio": "音频", "other": "其他",
    # "通用" 不从 category 推, 必须 definition 文件里显式写
}


def _workflow_group(name: str, cfg: dict) -> str:
    """读 preset 的 group, 缺省从 category 推."""
    if cfg.get("group"):
        return cfg["group"]
    return _NAV_GROUP_BY_CATEGORY.get(cfg.get("category", "other"), "其他")


def _workflows_for_nav():
    """返回前端 nav 用的工作流元信息列表 (跟 /api/workflows 一致)."""
    out = []
    for w in config.list_workflows():
        cfg = config.preset_config(w["name"])
        cat = cfg.get("category", "other")
        grp = _workflow_group(w["name"], cfg)
        out.append({
            "name": w["name"],
            "display_name": cfg.get("display_name", w["name"]),
            "description": cfg.get("description", ""),
            "category": cat,
            "group": grp,
            "output_kind": config.resolve_output_kind(cfg),
        })
    return out


# ============================================================
# 静态资源: ComfyUI input 目录文件 (example 文件在这里)
# ============================================================

@app.route("/comfy_output")
def comfy_output():
    """同源代理 ComfyUI /view，供局域网浏览器读取生成产物。"""
    filename = request.args.get("filename", "").strip()
    kind = request.args.get("type", "output").strip()
    subfolder = request.args.get("subfolder", "").strip()
    if not filename:
        return jsonify({"error": "missing filename"}), 400
    if kind not in {"input", "output", "temp"}:
        return jsonify({"error": "type must be input, output or temp"}), 400
    try:
        upstream = requests.get(
            scail2_client.get_base_url() + "/view",
            params={"filename": filename, "type": kind, "subfolder": subfolder},
            stream=True, timeout=(5, 120),
        )
    except (requests.ConnectionError, requests.Timeout) as e:
        return jsonify({"error": f"cannot read ComfyUI output: {e}"}), 502

    headers = {"Cache-Control": "no-store"}
    for key in ("Content-Type", "Content-Length", "Content-Disposition", "ETag", "Last-Modified"):
        value = upstream.headers.get(key)
        if value:
            headers[key] = value

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return Response(stream_with_context(generate()), status=upstream.status_code, headers=headers)


@app.route("/comfy_input/<path:filename>")
def comfy_input(filename):
    """提供 ComfyUI input 目录下的文件 (example 图片/视频).

    用于前端显示 example 的参考图/参考视频缩略图.
    ComfyUI 自己的 /view 也可以, 但那需要 ComfyUI 在跑; 这里直接读本地文件.
    """
    input_dir = config.COMFY_INPUT_DIR
    if not input_dir.exists():
        return jsonify({"error": "ComfyUI input dir not found"}), 404
    try:
        return send_from_directory(str(input_dir), filename)
    except FileNotFoundError:
        return jsonify({"error": f"file not found: {filename}"}), 404

@app.route("/example_thumb/<path:filename>")
def example_thumb(filename):
    """example 缩略图路由: 只查 app/static/examples/, 不再走 COMFY_INPUT_DIR.

    设计原则 (review 2026-07-28): 所有 example 用的素材 (preview + reference / drive / ref_audio)
    都打包在项目仓库 app/static/examples/ 下, 不依赖用户机器上 ComfyUI input 目录有什么.
    - 用户上传的本地文件 -> 走 /comfy_input/ (用户主动行为, 上传到 input 是合理的)
    - example 用的资源 -> 走 /example_thumb/ (项目自包含, 克隆即用)
    - 实际运行结果 -> 走 /comfy_output_proxy/ (ComfyUI 跑出来的, 自然在 ComfyUI)

    对 double 资源 (sca12/klein_edit 在 project + ComfyUI input 都有) 也不再有歧义:
    一律从 project 走, 用户自己新上传的文件不会"撞名"覆盖 example.
    """
    from pathlib import Path as _P
    base = _P(filename).name  # 防目录遍历
    if not base:
        return jsonify({"error": "empty filename"}), 400
    p = config.REPO_ROOT / "app" / "static" / "examples" / base
    if p.exists():
        return send_from_directory(str(config.REPO_ROOT / "app" / "static" / "examples"), base)
    return jsonify({"error": f"file not in project examples: {base}"}), 404


# 全局 context processor — 所有模板都能用 workbench_version
@app.context_processor
def _inject_globals():
    return {"workbench_version": config.WORKBENCH_VERSION}


@app.route("/")
def index():
    """运行页."""
    tid = theme._load_saved_theme()
    # 每个 preset 的 cfg 也在服务端预渲染, 前端不用 fetch /api/preset_cfg/<name>
    preset_cfgs = {}
    for w in config.list_workflows():
        cfg = config.preset_config(w["name"])
        ex = cfg.get("example", {}) or {}
        # example 里的 preview_image / preview_video / preview_audio 是相对仓库路径
        # (e.g. "app/static/examples/xxx.png"). Flask 端转成 /static/examples/xxx.png URL.
        preview_url = None
        for k in ("preview_video", "preview_image", "preview_audio"):
            raw = ex.get(k)
            if raw:
                # 形如 "app/static/examples/x.png" -> 剥前缀, 用 url_for
                rel = str(raw).replace("\\", "/")
                for prefix in ("app/static/", "static/"):
                    if rel.startswith(prefix):
                        rel = rel[len(prefix):]
                        break
                preview_url = url_for("static", filename=rel)
                break
        preset_cfgs[w["name"]] = {
            "name": w["name"],
            "display_name": cfg.get("display_name", w["name"]),
            "description": cfg.get("description", ""),
            "category": cfg.get("category", "other"),
            "output_kind": config.resolve_output_kind(cfg),
            "user_facing_inputs": cfg.get("user_facing_inputs", []),
            "preview_url": preview_url,
            "preview_kind": (
                "video" if ex.get("preview_video") else
                "audio" if ex.get("preview_audio") else "image"
            ) if preview_url else None,
        }
    return render_template(
        "run.html",
        workflows=_workflows_for_nav(),
        preset_cfgs=preset_cfgs,
        theme_css_content=theme._strip_style_tag(theme._apply_theme(tid)),
        page_bg_color=theme._theme_page_bg_color(tid),
        theme_id=tid,
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
        page_bg_color=theme._theme_page_bg_color(tid),
        theme_id=tid,
    )


@app.route("/wizard")
def wizard_page():
    """工作流向导页."""
    tid = theme._load_saved_theme()
    return render_template(
        "wizard.html",
        theme_css_content=theme._strip_style_tag(theme._apply_theme(tid)),
        page_bg_color=theme._theme_page_bg_color(tid),
        theme_id=tid,
    )


@app.route("/about")
def about_page():
    """关于页: 作者 + 工作台两个 section."""
    tid = theme._load_saved_theme()
    return render_template(
        "about.html",
        theme_css_content=theme._strip_style_tag(theme._apply_theme(tid)),
        page_bg_color=theme._theme_page_bg_color(tid),
        theme_id=tid,
    )


# ============================================================
# API 路由 — 主题
# ============================================================

@app.route("/api/themes")
def get_themes():
    """所有主题列表."""
    # review 2026-07-28: 加 tokens 字段, 设置页 swatch 预览要拿 --bg-app / --theme-accent-400 / --text-primary
    return jsonify([
        {"id": t["id"], "name": t["name"], "desc": t["desc"], "tokens": t.get("tokens", {})}
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
        "page_bg_color": theme._theme_page_bg_color(tid),
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
        "page_bg_color": theme._theme_page_bg_color(tid),
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
    return jsonify(_load_last_run(preset_name, cfg["user_facing_inputs"]))


@app.route("/api/last_output/<preset_name>")
def get_last_output(preset_name):
    """返回该 preset 最近一次成功 run 的首个输出 view URL.

    给"最近输出"按钮用: 从 history manifest 取最近 success 记录的 output/outputs[0],
    拼 /comfy_output?... 同源代理 URL. 没跑过成功记录则 available=false (按钮隐藏).
    """
    from app import history
    runs = history.list_runs(preset=preset_name, status="success", limit=1)
    if not runs:
        return jsonify({"available": False})
    manifest = runs[0]
    # 优先 outputs[0] (多图), 其次 output (单图)
    out = None
    outputs = manifest.get("outputs") or []
    if outputs:
        out = outputs[0]
    elif manifest.get("output"):
        out = manifest["output"]
    if not out or not out.get("filename"):
        return jsonify({"available": False})
    url = history.make_view_url(
        out["filename"], out.get("subfolder", ""), out.get("type", "output"))
    return jsonify({"available": True, "url": url, "filename": out["filename"]})


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
            "output_kind": config.resolve_output_kind(cfg),
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
        specs = config.preset_config(name)["user_facing_inputs"]
        _save_last_run(name, vals, specs)

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
    if kind == "audio":
        allowed = config.ALLOWED_AUDIO_EXT
        max_mb = config.MAX_AUDIO_MB
    elif kind == "video":
        allowed = config.ALLOWED_VIDEO_EXT
        max_mb = config.MAX_VIDEO_MB
    else:
        allowed = config.ALLOWED_IMAGE_EXT
        max_mb = config.MAX_IMAGE_MB
    if ext not in allowed:
        return jsonify({
            "error": f"extension {ext} not allowed (allowed: {sorted(allowed)})",
        }), 400

    # 校验大小
    f.stream.seek(0, 2)
    size = f.stream.tell()
    f.stream.seek(0)
    size_mb = size / (1024 * 1024)
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
        "output_kind": config.resolve_output_kind(cfg),
        "user_facing_inputs": cfg.get("user_facing_inputs", []),
    })


# ============================================================
# 工作流向导 API (workflow-decouple-wizard 2026-07-24)
# 引导用户把 ComfyUI workflow JSON 变成 preset definition, 不用手工编辑 JSON.
# workflow 在 parse 时存到 app/data/wizard/<token>.json, run/save 用 token 引用.
# ============================================================

import secrets

_WIZARD_DIR = config.REPO_ROOT / "app" / "data" / "wizard"


def _wizard_path(token: str) -> Path:
    return _WIZARD_DIR / f"{token}.json"


@app.route("/api/wizard/editable-workflows")
def wizard_editable_workflows():
    return jsonify(workflow_editor.list_editable_workflows())


@app.route("/api/wizard/definition/<preset_name>")
def wizard_editor_definition(preset_name):
    try:
        return jsonify(workflow_editor.get_editor_definition(preset_name))
    except KeyError as e:
        return jsonify({"error": str(e)}), 404


@app.route("/api/wizard/definition/<preset_name>/inputs", methods=["PUT"])
def wizard_save_input_layout(preset_name):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(workflow_editor.save_input_layout(preset_name, data.get("inputs")))
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/wizard/definition/<preset_name>/override", methods=["DELETE"])
def wizard_restore_input_layout(preset_name):
    try:
        restored = workflow_editor.restore_input_layout(preset_name)
        return jsonify({"name": preset_name, "restored": restored})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/wizard/preset-order", methods=["PUT"])
def wizard_save_preset_order():
    """按新顺序重排工作流. body: {"order": [name1, name2, ...]}.

    写回 definition 文件. 10 步长分配 order, 留空间给后续插入.
    """
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(workflow_editor.save_preset_order(data.get("order")))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/wizard/parse", methods=["POST"])
def wizard_parse():
    """步骤 A: 上传 ComfyUI API 格式 workflow JSON → 返回推断后的候选输入字段.

    POST body: {"workflow_json": "<raw json string>"}
    返回: {"token": "...", "fields": [...], "node_count": N}
    workflow 存到 app/data/wizard/<token>.json, 后续 run/save 用 token.
    """
    data = request.get_json(silent=True) or {}
    raw = data.get("workflow_json")
    if not raw or not isinstance(raw, str):
        return jsonify({"error": "missing workflow_json (ComfyUI API 格式 JSON 字符串)"}), 400
    try:
        parsed = wizard.parse_workflow_api_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        return jsonify({"error": f"workflow JSON 解析失败: {e}"}), 400

    token = secrets.token_hex(8)
    _WIZARD_DIR.mkdir(parents=True, exist_ok=True)
    _wizard_path(token).write_text(
        json.dumps(parsed["workflow"], ensure_ascii=False), encoding="utf-8")
    return jsonify({
        "token": token,
        "fields": parsed["fields"],
        "node_count": parsed["node_count"],
    })


@app.route("/api/wizard/run", methods=["POST"])
def wizard_run():
    """步骤 B: 用向导确认的输入跑一次 workflow → 返回所有输出 node 的产物.

    POST body: {"token": "...", "fields": [...], "values": {...}}
    返回: {"outputs": [{node_id, title, media_key, filename, type, url}, ...]}
    需要 ComfyUI 在跑.
    """
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    fields = data.get("fields", [])
    values = data.get("values", {})
    wf_path = _wizard_path(token) if token else None
    if not wf_path or not wf_path.exists():
        return jsonify({"error": "invalid or expired token, 请重新上传 workflow"}), 400
    if not isinstance(fields, list):
        return jsonify({"error": "fields 必须是数组"}), 400

    workflow = json.loads(wf_path.read_text(encoding="utf-8"))
    try:
        replacements = wizard.build_replacements(fields, values)
        history = wizard.run_workflow_once(workflow, replacements)
    except Exception as e:
        return jsonify({"error": f"运行失败: {e}"}), 500

    outputs = wizard.extract_all_outputs(history, workflow)
    if not outputs:
        return jsonify({"error": "运行完成但没有输出产物, 检查 workflow 是否有输出节点"}), 422
    return jsonify({"outputs": outputs})


@app.route("/api/wizard/save", methods=["POST"])
def wizard_save():
    """步骤 C: 把向导结果存成 preset definition.

    POST body: {
        "token": "...", "name": "my_workflow", "display_name": "...",
        "fields": [...] (用户最终确认的 user_facing_inputs),
        "output_node_id": "456", "output_kind": "video",
        "example": {...} (可选, 默认用这次跑的输入),
    }
    返回: {"name": ..., "definition_path": ...}
    """
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "missing name"}), 400
    # name 只允许小写字母数字下划线 (变成文件名)
    if not all(c.isalnum() or c == "_" for c in name) or not name[0].isalpha():
        return jsonify({"error": "name 只能含字母数字下划线, 且以字母开头"}), 400

    wf_path = _wizard_path(token) if token else None
    if not wf_path or not wf_path.exists():
        return jsonify({"error": "invalid or expired token"}), 400
    # 已存在的 preset 名不允许覆盖 (避免误删作者手写的 definition)
    existing = {w["name"] for w in config.list_workflows()}
    if name in existing:
        return jsonify({"error": f"preset '{name}' 已存在, 换个名字"}), 409

    workflow = json.loads(wf_path.read_text(encoding="utf-8"))
    fields = data.get("fields", [])
    example = data.get("example") or {}
    if data.get("selected_output"):
        try:
            example = wizard.prepare_example(
                name, fields, data.get("values", {}), data["selected_output"]
            )
        except (FileNotFoundError, OSError, ValueError) as e:
            return jsonify({"error": f"示例素材保存失败: {e}"}), 422
    cfg = {
        "workflow_file": _save_workflow_template(name, workflow),
        "display_name": data.get("display_name") or name,
        "category": data.get("category", "other"),
        "order": data.get("order", 999),
        "description": data.get("description", ""),
        "user_facing_inputs": fields,
        "output_kind": data.get("output_kind", "video"),
        "example": example,
    }
    if data.get("output_node_id"):
        cfg["do_not_modify_warnings"] = [{
            "node_id": str(data["output_node_id"]),
            "reason": "向导标记的最终用户输出节点",
        }]
    out = config.save_definition(name, cfg)
    # 清理临时 workflow
    try:
        wf_path.unlink()
    except OSError:
        pass
    try:
        rel = str(out.relative_to(config.REPO_ROOT))
    except ValueError:
        rel = str(out)
    return jsonify({"name": name, "definition_path": rel})


def _save_workflow_template(name: str, workflow: dict) -> str:
    """把向导上传的 workflow 存成 app/presets/<name>.json, 返回文件名."""
    fname = f"{name}.json"
    out = config.PRESETS_DIR / fname
    out.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return fname


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
