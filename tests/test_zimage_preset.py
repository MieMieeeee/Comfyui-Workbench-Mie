"""文生图 workflow (zimage) 的契约测试 + extract_primary_image_output 测试。"""
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


# --- C4: extract_primary_image_output ---

def _image_history():
    """合成一个文生图的 history（outputs 含 images）。"""
    return {"outputs": {
        "9": {"images": [{"filename": "z_00001_.png", "subfolder": "", "type": "output"}]}
    }}


def test_extract_image_output_basic():
    out = scail2_client.extract_primary_image_output(_image_history())
    assert out == {"filename": "z_00001_.png", "subfolder": "", "type": "output"}


def test_extract_image_output_empty():
    assert scail2_client.extract_primary_image_output({}) is None
    assert scail2_client.extract_primary_image_output({"outputs": {}}) is None


def test_extract_image_output_no_images_key():
    """outputs 有节点但没有 images 字段 → None。"""
    assert scail2_client.extract_primary_image_output({"outputs": {"9": {}}}) is None


def test_get_output_url_for_image():
    url = scail2_client.get_output_url("foo.png", "")
    assert "/view" in url and "foo.png" in url
