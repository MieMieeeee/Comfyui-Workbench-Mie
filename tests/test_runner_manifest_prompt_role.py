"""runner.build_manifest 的 prompt 字段应支持 spec.manifest_role (数据驱动).

Bug: run_workflow 里硬编码 node_id 360/362/348/6 写 manifest 的 prompt 字段,
导致非 SCAIL-2 preset (zimage/qwen_image 等) 的 ref_prompt/drive_prompt 永远空.
fix: 给 text spec 加 manifest_role, runner 从 spec 收集, 缺失时回退老 node_id 兜底.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app.services import runner


def test_resolve_prompt_meta_from_manifest_role():
    """spec 声明 manifest_role 时, _resolve_prompt_meta 优先从 spec 取值."""
    inputs_spec = [
        {"node_id": "100", "field": "text", "type": "text",
         "manifest_role": "main_prompt"},
        {"node_id": "200", "field": "text", "type": "text",
         "manifest_role": "ref_prompt"},
        {"node_id": "300", "field": "text", "type": "text",
         "manifest_role": "drive_prompt"},
    ]
    text_by_field = {
        ("100", "text"): "a cat",
        ("200", "text"): "person mask",
        ("300", "text"): "drive mask",
    }
    main, ref, drive = runner._resolve_prompt_meta(inputs_spec, text_by_field)
    assert main == "a cat"
    assert ref == "person mask"
    assert drive == "drive mask"


def test_resolve_prompt_meta_fallback_to_legacy_node_ids():
    """没有 manifest_role 时回退到 SCAIL-2 老 node_id 360/362/348 (行为锁)."""
    inputs_spec = [
        {"node_id": "360", "field": "text", "type": "text"},  # main
        {"node_id": "362", "field": "text", "type": "text"},  # ref
        {"node_id": "348", "field": "text", "type": "text"},  # drive
    ]
    text_by_field = {
        ("360", "text"): "main text",
        ("362", "text"): "ref text",
        ("348", "text"): "drive text",
    }
    main, ref, drive = runner._resolve_prompt_meta(inputs_spec, text_by_field)
    assert main == "main text"
    assert ref == "ref text"
    assert drive == "drive text"


def test_resolve_prompt_meta_missing_returns_empty():
    """spec 既无 manifest_role 也无兜底 node_id -> 返回空串 (不抛)."""
    inputs_spec = [
        {"node_id": "999", "field": "text", "type": "text"},
    ]
    main, ref, drive = runner._resolve_prompt_meta(inputs_spec, {})
    assert main == ""
    assert ref == ""
    assert drive == ""


def test_resolve_prompt_meta_mixed():
    """部分 spec 带 manifest_role, 部分走兜底 (迁移中途的混合态)."""
    inputs_spec = [
        {"node_id": "100", "field": "text", "type": "text",
         "manifest_role": "main_prompt"},  # 显式
        # ref/drive 走兜底 362/348
        {"node_id": "362", "field": "text", "type": "text"},
        {"node_id": "348", "field": "text", "type": "text"},
    ]
    text_by_field = {
        ("100", "text"): "explicit main",
        ("362", "text"): "legacy ref",
        ("348", "text"): "legacy drive",
    }
    main, ref, drive = runner._resolve_prompt_meta(inputs_spec, text_by_field)
    assert main == "explicit main"
    assert ref == "legacy ref"
    assert drive == "legacy drive"
