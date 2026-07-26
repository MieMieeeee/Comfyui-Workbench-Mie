"""Flask 路由测试 — 锁每个非流式 API 的契约.

步骤 2 范围: 非流式路由. SSE 流式 (/api/run/<preset>) 在步骤 4.
文件上传 (/api/upload) 在步骤 5.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import flask_app


@pytest.fixture
def client():
    """Flask test client. 每个 test 独立."""
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


# ============================================================
# SSE 流式运行 (步骤 4)
# ============================================================

def test_run_unknown_preset_returns_404(client):
    """POST /api/run/<不存在的 preset> 返回 404."""
    r = client.post("/api/run/__nonexistent__", json={"form_values": []})
    assert r.status_code == 404


def test_run_invalid_body_returns_400(client):
    """POST /api/run/<preset> form_values 不是 list 返回 400."""
    from app import config
    preset = config.list_workflows()[0]["name"]
    r = client.post(f"/api/run/{preset}", json={"form_values": "not a list"})
    assert r.status_code == 400


def test_run_returns_event_stream(client):
    """POST /api/run/<preset> 返回 text/event-stream mimetype."""
    from app import config
    preset = config.list_workflows()[0]["name"]
    # 不实际跑 ComfyUI (会失败但 SSE 应该 still 返回 stream)
    r = client.post(f"/api/run/{preset}", json={"form_values": []})
    assert r.status_code == 200
    assert "text/event-stream" in r.content_type
    # 内容应该是 SSE 格式 (data: ... 开头)
    body = r.data.decode("utf-8")
    assert "data:" in body
    # 末尾应该有 [DONE]
    assert "[DONE]" in body


def test_run_event_has_json_payload(client):
    """SSE data 行能解析成 JSON, 含 type 字段."""
    from app import config
    import json as _json
    preset = config.list_workflows()[0]["name"]
    r = client.post(f"/api/run/{preset}", json={"form_values": []})
    body = r.data.decode("utf-8")
    # 找第一个 data: 行 (排除 [DONE])
    for line in body.split("\n"):
        if line.startswith("data: ") and "[DONE]" not in line:
            payload = _json.loads(line[len("data: "):])
            assert "type" in payload
            assert payload["type"] in ("log", "media", "error", "done")
            break
    else:
        pytest.fail("没找到 data: 事件行")


def test_run_to_sse_serializes_tuple_progress():
    """RunEvent.to_sse 把 progress tuple 转成 list (JSON 不支持 tuple)."""
    from app.services.runner import RunEvent
    ev = RunEvent(type="log", progress=(5, 20))
    sse = ev.to_sse()
    assert '"progress": [5, 20]' in sse  # list 不是 tuple
    assert "[DONE]" not in sse


# ============================================================
# 文件上传 (步骤 5)
# ============================================================

def test_upload_no_file_returns_400(client):
    """POST /api/upload 没有 file 字段返回 400."""
    r = client.post("/api/upload")
    assert r.status_code == 400


def test_upload_bad_extension_returns_400(client):
    """POST /api/upload 扩展名不允许返回 400."""
    import io
    r = client.post("/api/upload",
                    data={"file": (io.BytesIO(b"x"), "evil.exe"), "kind": "image"},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    data = r.get_json()
    assert "error" in data
    assert "not allowed" in data["error"] or "extension" in data["error"].lower()


def test_upload_calls_comfy_upload(monkeypatch):
    """上传合法文件时调用 scail2_client.upload, 返回 ComfyUI 给的 name."""
    # 用 monkeypatch 替换 scail2_client.upload, 避免真连 ComfyUI
    import io
    from app import flask_app as fa
    from app import scail2_client

    def fake_upload(file_path, kind="image"):
        return {"name": "uploaded_name.png", "subfolder": "", "type": "input"}

    monkeypatch.setattr(scail2_client, "upload", fake_upload)

    fa.app.config["TESTING"] = True
    with fa.app.test_client() as c:
        r = c.post("/api/upload",
                   data={"file": (io.BytesIO(b"fake-png-content"), "test.png"), "kind": "image"},
                   content_type="multipart/form-data")
    assert r.status_code == 200
    data = r.get_json()
    assert data["name"] == "uploaded_name.png"
    assert data["type"] == "input"

def test_index_returns_html(client):
    """GET / 返回运行页 HTML (200)."""
    r = client.get("/")
    assert r.status_code == 200
    assert b"ComfyUI" in r.data or b"comfyui" in r.data


def test_settings_page_returns_html(client):
    """GET /settings 返回设置页 HTML."""
    r = client.get("/settings")
    assert r.status_code == 200


# ============================================================
# 主题相关
# ============================================================

def test_get_themes_returns_list(client):
    """GET /api/themes 返回所有主题列表 (id/name/desc)."""
    r = client.get("/api/themes")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    assert len(data) > 0
    # 每个主题必须有 id / name
    for t in data:
        assert "id" in t
        assert "name" in t


def test_get_current_theme_returns_id(client):
    """GET /api/theme 返回当前主题 id + css + desc."""
    r = client.get("/api/theme")
    assert r.status_code == 200
    data = r.get_json()
    assert "theme_id" in data
    assert "css" in data  # _apply_theme 产出的 <style>:root{...}</style>


def test_set_theme_persists(client, monkeypatch):
    """POST /api/theme 切换主题并持久化."""
    from app.services import theme
    # 用临时文件避免污染真实 theme_settings.json
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        pass
    from app import config
    monkeypatch.setattr(config, "THEME_SETTINGS_FILE", Path(tf.name))
    # 重新加载 theme 模块的 _THEMES_CACHE 以防 stale
    theme._THEMES_CACHE = None

    r = client.post("/api/theme", json={"theme_id": "coral-orange"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["theme_id"] == "coral-orange"
    assert "css" in data


# ============================================================
# 示例 / 上次参数
# ============================================================

def test_get_example_returns_values(client):
    """GET /api/example/<preset> 返回 example 表单值列表."""
    from app import config
    workflows = config.list_workflows()
    assert workflows, "需要至少一个 preset"
    preset = workflows[0]["name"]

    r = client.get(f"/api/example/{preset}")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    assert len(data) > 0


def test_get_example_unknown_preset_returns_404(client):
    """GET /api/example/<不存在的 preset> 返回 404."""
    r = client.get("/api/example/__nonexistent_preset__")
    assert r.status_code == 404


def test_get_last_run_returns_list(client):
    """GET /api/last_run/<preset> 返回 last_run 列表 (没跑过也返全 None)."""
    from app import config
    preset = config.list_workflows()[0]["name"]

    r = client.get(f"/api/last_run/{preset}")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)


# ============================================================
# ComfyUI 连接状态
# ============================================================

def test_get_comfy_status(client):
    """GET /api/comfy_status 返回连接状态 (ok bool + text)."""
    r = client.get("/api/comfy_status")
    assert r.status_code == 200
    data = r.get_json()
    assert "ok" in data
    assert isinstance(data["ok"], bool)
    assert "url" in data


# ============================================================
# 设置 tab URL 操作
# ============================================================

def test_save_url(client):
    """POST /api/settings/url 保存 URL + 测试连通性."""
    r = client.post("/api/settings/url", json={"url": "http://127.0.0.1:8188"})
    assert r.status_code == 200
    data = r.get_json()
    assert "message" in data


def test_reset_url(client):
    """POST /api/settings/url/reset 恢复默认 URL."""
    r = client.post("/api/settings/url/reset")
    assert r.status_code == 200
    data = r.get_json()
    assert "url" in data
    assert "message" in data


def test_test_url(client):
    """GET /api/settings/url/test 重新测试连通性."""
    r = client.get("/api/settings/url/test")
    assert r.status_code == 200
    data = r.get_json()
    assert "message" in data


# ============================================================
# 健康检查
# ============================================================

def test_health_check(client):
    """GET /api/health 返回 markdown 报告 (可能很慢, 但 200)."""
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.get_json()
    assert "report" in data  # markdown 字符串


# ============================================================
# 随机提示词
# ============================================================

def test_random_prompt(client):
    """GET /api/random_prompt 返回单条提示词."""
    r = client.get("/api/random_prompt")
    assert r.status_code == 200
    data = r.get_json()
    assert "prompt" in data
    assert isinstance(data["prompt"], str)


def test_random_prompt_n3(client):
    """GET /api/random_prompt?n=3 返回 3 条 (用 \\n---\\n 分隔)."""
    r = client.get("/api/random_prompt?n=3")
    assert r.status_code == 200
    data = r.get_json()
    assert "prompt" in data


# ============================================================
# 段数预估
# ============================================================

def test_estimated_segments_no_video(client):
    """GET /api/estimated_segments 无 drive_path 返回提示文本."""
    r = client.get("/api/estimated_segments")
    assert r.status_code == 200
    data = r.get_json()
    assert "markdown" in data


# ============================================================
# 打开输出目录
# ============================================================

def test_open_output_dir_removed(client):
    """备忘: /api/open_output_dir 接口被完全删除.

    原本这个接口调本地 explorer/open, 但 WebUI 可能从局域网访问远程服务器,
    调本地文件管理器只会在服务器本机打开. 中间试过 "return 路径 + 复制到剪贴板"
    也不合适: 用户远程访问时看不到服务器路径 (不是本地路径), 也不走 ComfyUI 自己的 /view。
    完全删除 —— 输出由 run 与 settings 两个页面通过 /comfy_output 代理看完整产物.
    """
    r = client.post("/api/open_output_dir")
    assert r.status_code == 404, "/api/open_output_dir 应该被删除"


# ============================================================
# Preset 列表 (供前端 nav 渲染)
# ============================================================

def test_get_workflows(client):
    """GET /api/workflows 返回所有 preset 元信息 (前端 nav 用)."""
    r = client.get("/api/workflows")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    assert len(data) > 0
    # 每个 preset 必须有 name / display_name
    for w in data:
        assert "name" in w
        assert "display_name" in w
