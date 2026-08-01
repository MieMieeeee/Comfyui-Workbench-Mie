"""wizard 落盘 definition 前应剥离向导运行期字段.

Bug: wizard 生成的 spec 带 class_type/confidence/current_value/node_title/enabled
等向导 UI 专用字段, 它们对 runner/form_schema/validator 无用, 却留在 definition
里增加体积 + 让 spec 语义复杂. fix: wizard_save 落盘前用 strip_runtime_fields 过滤.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app.services import wizard


# 向导运行期专用字段 (要被剥离)
_RUNTIME_FIELDS = {"class_type", "confidence", "current_value", "node_title",
                   "enabled", "_merge_key"}


def test_strip_runtime_fields_removes_all_runtime_keys():
    spec = {
        "node_id": "5",
        "field": "text",
        "type": "text",
        "label": "提示词",
        "default": "a cat",
        "help": "...",
        "tier": "basic",
        "max_chars": 2000,
        "example_key": "text",
        # 运行期字段:
        "class_type": "CLIPTextEncode",
        "confidence": "medium",
        "current_value": "a cat",
        "node_title": "CLIP Text Encode",
        "enabled": True,
        "_merge_key": "5",
    }
    stripped = wizard.strip_runtime_fields(spec)
    for bad in _RUNTIME_FIELDS:
        assert bad not in stripped, f"剥离后仍含运行期字段 {bad!r}: {stripped}"
    # 运行需要的字段保留
    for keep in ("node_id", "field", "type", "label", "default", "help",
                 "tier", "max_chars", "example_key"):
        assert keep in stripped, f"误删了运行字段 {keep!r}: {stripped}"


def test_strip_runtime_fields_idempotent():
    """已经干净的 spec 再 strip 不变."""
    clean = {"node_id": "5", "field": "text", "type": "text", "default": "x"}
    assert wizard.strip_runtime_fields(clean) == clean


def test_strip_runtime_fields_keeps_manifest_role():
    """manifest_role (review #4 加的) 必须保留, 它是运行时字段."""
    spec = {
        "node_id": "360", "field": "text", "type": "text",
        "manifest_role": "main_prompt",
        "confidence": "medium",
    }
    stripped = wizard.strip_runtime_fields(spec)
    assert stripped.get("manifest_role") == "main_prompt"
    assert "confidence" not in stripped


def test_strip_runtime_fields_handles_missing():
    """空 dict / 缺字段不抛."""
    assert wizard.strip_runtime_fields({}) == {}
    assert wizard.strip_runtime_fields({"node_id": "1"}) == {"node_id": "1"}


def test_strip_runtime_fields_does_not_mutate_input():
    """不污染入参 (返回新 dict)."""
    spec = {"node_id": "5", "type": "text", "confidence": "high", "enabled": True}
    _ = wizard.strip_runtime_fields(spec)
    assert spec.get("confidence") == "high"
    assert spec.get("enabled") is True
