"""run_image_workflow 只支持 text/image_sizes/int_random/int/float.

Bug: 它的 else 分支静默丢弃 file:image/file:video/file:audio/bool 等 type.
带 image_sizes + file:image 的图生图 preset 会被 stream_events 错路由到
run_image_workflow, 参考图被默默忽略. fix: run_image_workflow 开头断言 +
stream_events 路由排除带 file 输入的 preset.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app.services import runner


def _make_cfg(inputs):
    return {
        "output_kind": "image",
        "user_facing_inputs": inputs,
    }


def test_stream_events_routes_image_with_file_to_run_workflow(monkeypatch):
    """image preset 带 file:image 应走通用 run_workflow, 不走 run_image_workflow."""
    cfg = _make_cfg([
        {"node_id": "1", "field": "image", "type": "file:image"},
        {"node_id": "2", "field": "sizes", "type": "image_sizes"},
        {"node_id": "3", "field": "seed", "type": "int_random"},
    ])
    chosen_fn = {}
    real_run = runner.run_workflow
    real_image = runner.run_image_workflow

    def fake_run(*a, **kw):
        chosen_fn["name"] = "run_workflow"
        return iter([])

    def fake_image(*a, **kw):
        chosen_fn["name"] = "run_image_workflow"
        return iter([])

    monkeypatch.setattr(runner, "run_workflow", fake_run)
    monkeypatch.setattr(runner, "run_image_workflow", fake_image)
    monkeypatch.setattr(runner.config, "preset_config", lambda n: cfg)

    list(runner.stream_events("test_preset", []))

    assert chosen_fn.get("name") == "run_workflow", (
        "带 file:image 的 image preset 应走 run_workflow, 实际走 "
        f"{chosen_fn.get('name')}")


def test_stream_events_routes_image_sizes_only_to_run_image(monkeypatch):
    """纯 image_sizes (无 file 输入) 的 image preset 仍走 run_image_workflow."""
    cfg = _make_cfg([
        {"node_id": "2", "field": "sizes", "type": "image_sizes"},
        {"node_id": "3", "field": "seed", "type": "int_random"},
        {"node_id": "5", "field": "text", "type": "text"},
    ])
    chosen_fn = {}

    def fake_run(*a, **kw):
        chosen_fn["name"] = "run_workflow"
        return iter([])

    def fake_image(*a, **kw):
        chosen_fn["name"] = "run_image_workflow"
        return iter([])

    monkeypatch.setattr(runner, "run_workflow", fake_run)
    monkeypatch.setattr(runner, "run_image_workflow", fake_image)
    monkeypatch.setattr(runner.config, "preset_config", lambda n: cfg)

    list(runner.stream_events("test_preset", []))

    assert chosen_fn.get("name") == "run_image_workflow"


def test_run_image_workflow_rejects_unsupported_type(monkeypatch):
    """run_image_workflow 开头断言: 不支持 file 类输入 -> 抛 _RunError."""
    cfg = _make_cfg([
        {"node_id": "1", "field": "image", "type": "file:image"},
        {"node_id": "2", "field": "sizes", "type": "image_sizes"},
    ])
    monkeypatch.setattr(runner.config, "preset_config", lambda n: cfg)
    # 直接调 generator 函数 (不经过 stream_events), 模拟错误路由
    gen = runner.run_image_workflow("test_preset", None, ["1024x1024"], None)
    with pytest.raises(runner._RunError) as exc_info:
        # 必须消费到抛错点 (生成器要 next 才执行)
        for _ in gen:
            pass
    assert "file" in str(exc_info.value).lower() or "run_workflow" in str(exc_info.value)
