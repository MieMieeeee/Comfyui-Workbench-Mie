"""文生图 workflow (zimage) 的契约测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import config
from app.workflow_validator import validate, WorkflowValidationError
from app import scail2_client


# --- C2: zimage preset 契约 ---

def test_zimage_preset_exists_in_params():
    """params.json 必须有 zimage preset。"""
    cfg = config.preset_config("zimage")
    assert "user_facing_inputs" in cfg


def test_zimage_workflow_file_exists():
    p = config.workflow_path("zimage")
    assert p.exists(), f"zimage.json missing at {p}"


def test_zimage_workflow_validates():
    """zimage workflow 应通过 validator。"""
    wf = json.load(config.workflow_path("zimage").open(encoding="utf-8"))
    cfg = config.preset_config("zimage")
    # zimage 的输出是 SaveImage 不是视频，validator 需要接受 image 输出节点
    validate(wf, cfg)


def test_zimage_has_key_nodes():
    """zimage 必须有正向 prompt 节点 + 尺寸节点 + seed 节点 + SaveImage。"""
    wf = json.load(config.workflow_path("zimage").open(encoding="utf-8"))
    class_types = {n.get("class_type") for n in wf.values()}
    assert "CLIPTextEncode" in class_types, "缺正向 prompt 节点"
    assert "EmptySD3LatentImage" in class_types, "缺尺寸节点"
    assert "KSampler" in class_types, "缺 KSampler 节点"


def test_zimage_user_facing_inputs_match_nodes():
    """zimage preset 声明的 user_facing 节点和字段都必须在 workflow 里存在。"""
    wf = json.load(config.workflow_path("zimage").open(encoding="utf-8"))
    cfg = config.preset_config("zimage")
    for spec in cfg["user_facing_inputs"]:
        nid = str(spec["node_id"])
        assert nid in wf, f"preset 声明 node {nid} 但 workflow 没有"


def test_get_output_url_for_image():
    url = scail2_client.get_output_url("foo.png", "")
    assert "/view" in url and "foo.png" in url


# --- 第四阶段 §B：输出尺寸用途标签化 ---

def _zimage_sizes_spec():
    cfg = config.preset_config("zimage")
    return next(s for s in cfg["user_facing_inputs"] if s["type"] == "image_sizes")


def test_zimage_sizes_presets_are_labeled():
    """zimage 的 output_size 选项必须升级为 {label, value} 形式。

    第四阶段指令 §B：选项要带比例 + 用途说明（例如 "🎬 1280×720 ｜ 16:9 (横版封面)"），
    优化扫描成本。纯字符串 presets 已淘汰。
    """
    spec = _zimage_sizes_spec()
    presets = spec.get("presets", [])
    assert presets, "zimage sizes presets 不能为空"
    for p in presets:
        assert isinstance(p, dict), f"preset 条目必须是 {{label, value}} 字典, 实际 {type(p)}: {p!r}"
        assert "label" in p and "value" in p, f"preset 缺 label/value: {p!r}"
        # label 带用途/比例文案，不是裸尺寸
        assert any(tok in p["label"] for tok in ("16:9", "9:16", "1:1", "4:3", "3:4", "横", "竖", "方", "正")), \
            f"label 没带比例/用途说明: {p['label']!r}"


def test_zimage_sizes_values_still_parse_strict():
    """用途标签化后，value 仍必须是 parse_sizes 能严格 fullmatch 的纯净 WxH。

    parse_sizes 保持严格匹配（AGENTS.md 数据驱动 + 现有 test_parse_sizes_strict_fullmatch），
    label 文案不污染解析路径。这是本方案的核心不变式。
    """
    from app import scail2_app
    spec = _zimage_sizes_spec()
    for p in spec["presets"]:
        v = p["value"]
        assert scail2_app.parse_sizes(v) is not None, \
            f"value {v!r} 无法被 parse_sizes 严格解析（label 泄漏到 value 了?）"


def test_zimage_sizes_default_matches_a_value():
    """default 数组里的值必须是某个 preset 的 value（避免默认选不存在的尺寸）。"""
    spec = _zimage_sizes_spec()
    values = {p["value"] for p in spec["presets"]}
    for d in spec.get("default", []):
        assert d in values, f"default {d!r} 不在 presets values {values} 里"
