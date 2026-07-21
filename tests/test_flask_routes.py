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
# 基础页面路由
# ============================================================

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

def test_open_output_dir(client):
    """POST /api/open_output_dir 触发打开, 返回状态文本."""
    r = client.post("/api/open_output_dir")
    assert r.status_code == 200
    data = r.get_json()
    assert "message" in data


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
