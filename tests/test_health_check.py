"""health_check 多层健康检查测试（mock requests，不碰网络）。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import health_check, config


# --- requirements 加载 ---

def test_load_requirements_has_models_and_nodes():
    req = health_check.load_requirements()
    assert "models" in req and "custom_nodes" in req
    assert len(req["models"]) == 10
    assert len(req["custom_nodes"]) >= 15


# --- L0 连通性 ---

def _mock_resp(status=200, json_body=None):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=json_body or {})
    r.text = "body"
    return r


SYSTEM_STATS_OK = {
    "system": {"comfyui_version": "0.3.14", "pytorch_version": "2.6.0"},
    "devices": [{"name": "NVIDIA GeForce RTX 4090", "type": "cuda",
                 "vram_total": 25769803776, "vram_free": 19565942784}],
}


def test_check_health_reachable_parses_gpu():
    """L0+L1：连通且 /system_stats 返回 GPU 信息。"""
    with patch("app.health_check.requests") as mock_req:
        mock_req.get.return_value = _mock_resp(200, SYSTEM_STATS_OK)
        mock_req.ConnectionError = Exception
        report = health_check.check_health("http://127.0.0.1:8188")
    assert report.reachable is True
    assert report.connect_error is None
    assert "RTX 4090" in (report.gpu_name or "")
    assert report.vram_total_gb is not None and report.vram_total_gb > 20
    assert report.comfyui_version == "0.3.14"


def test_check_health_connection_refused_diagnosis():
    """L0 失败：连接被拒 → connect_error 含'没有进程监听'（可操作诊断）。"""
    import requests as real_req
    with patch("app.health_check.requests") as mock_req:
        mock_req.ConnectionError = real_req.ConnectionError
        mock_req.Timeout = real_req.Timeout
        mock_req.get.side_effect = real_req.ConnectionError(
            "[Errno 111] Connection refused")
        report = health_check.check_health("http://127.0.0.1:8188")
    assert report.reachable is False
    assert report.connect_error is not None
    assert "监听" in report.connect_error or "启动" in report.connect_error


def test_check_health_timeout_diagnosis():
    import requests as real_req
    with patch("app.health_check.requests") as mock_req:
        mock_req.ConnectionError = real_req.ConnectionError
        mock_req.Timeout = real_req.Timeout
        mock_req.get.side_effect = real_req.Timeout("timed out")
        report = health_check.check_health("http://10.0.0.99:8188")
    assert report.reachable is False
    assert "超时" in (report.connect_error or "")


def test_check_health_unreachable_host_diagnosis():
    import requests as real_req
    with patch("app.health_check.requests") as mock_req:
        mock_req.ConnectionError = real_req.ConnectionError
        mock_req.Timeout = real_req.Timeout
        mock_req.get.side_effect = real_req.ConnectionError(
            "Failed to resolve 'nonexistent-host'")
        report = health_check.check_health("http://nonexistent-host:8188")
    assert report.reachable is False
    assert report.connect_error is not None


# --- L2 模型检查 ---

def _object_info_with_models(present_filenames: set[str]):
    """构造 /object_info 响应：loader 节点的 input 列出 present 的模型。"""
    obj = {}
    for node, field in [("UNETLoader", "unet_name"), ("VAELoader", "vae_name"),
                        ("CLIPLoader", "clip_name"), ("CLIPVisionLoader", "clip_name"),
                        ("CheckpointLoaderSimple", "ckpt_name"), ("LoraLoaderModelOnly", "lora_name")]:
        obj[node] = {"input": {"required": {field: [sorted(present_filenames), {}]}}}
    # 也注册一些 class_type 供 L3
    for ct in ["KSampler", "SaveImage", "EmptySD3LatentImage", "CLIPTextEncode", "VAEDecode"]:
        obj[ct] = {"input": {"required": {}}}
    return obj


def test_check_health_models_all_present():
    files = {
        "SCAIL-2\\wan2.1_14B_SCAIL_2_fp8_scaled.safetensors",
        "Wan_2.1\\wan_2.1_vae.safetensors",
        "Wan\\umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "clip_vision_h.safetensors",
        "sam3.1_multiplex_fp16.safetensors",
        "Wan2.1\\lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors",
        "Scail-2\\wan2.1_SCAIL_2_DPO_lora_bf16.safetensors",
        "Z-Image-Turbo\\z_image_turbo_bf16.safetensors",
        "Flux\\ae.sft",
        "Qwen\\qwen_3_4b.safetensors",
    }
    obj = _object_info_with_models(files)
    obj_keys = set(obj.keys())
    responses = [_mock_resp(200, SYSTEM_STATS_OK), _mock_resp(200, obj)]
    with patch("app.health_check.requests") as mock_req:
        mock_req.ConnectionError = Exception
        mock_req.Timeout = Exception
        mock_req.get.side_effect = responses
        report = health_check.check_health("http://x:8188")
    assert report.reachable is True
    assert report.missing_models == []


def test_check_health_models_missing_listed():
    """缺一个模型 → missing_models 含它。"""
    files = {  # 故意缺 sam3.1_multiplex_fp16
        "SCAIL-2\\wan2.1_14B_SCAIL_2_fp8_scaled.safetensors",
        "Wan_2.1\\wan_2.1_vae.safetensors",
        "Wan\\umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "clip_vision_h.safetensors",
        "Wan2.1\\lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors",
        "Scail-2\\wan2.1_SCAIL_2_DPO_lora_bf16.safetensors",
    }
    obj = _object_info_with_models(files)
    with patch("app.health_check.requests") as mock_req:
        mock_req.ConnectionError = Exception
        mock_req.Timeout = Exception
        mock_req.get.side_effect = [_mock_resp(200, SYSTEM_STATS_OK), _mock_resp(200, obj)]
        report = health_check.check_health("http://x:8188")
    filenames = [m.filename for m in report.missing_models]
    assert any("sam3.1_multiplex" in f for f in filenames)


# --- L3 自定义节点 ---

def test_check_health_nodes_missing():
    """缺自定义节点 class_type → missing_nodes 含它 + 推测包名。"""
    files = set()
    obj = _object_info_with_models(files)
    # 只注册核心节点，不注册 SAM3_VideoTrack 等
    with patch("app.health_check.requests") as mock_req:
        mock_req.ConnectionError = Exception
        mock_req.Timeout = Exception
        mock_req.get.side_effect = [_mock_resp(200, SYSTEM_STATS_OK), _mock_resp(200, obj)]
        report = health_check.check_health("http://x:8188")
    missing_classes = [n.class_type for n in report.missing_nodes]
    assert "SAM3_VideoTrack" in missing_classes
    assert "VHS_VideoCombine" in missing_classes
    # 推测包名
    sam3 = [n for n in report.missing_nodes if n.class_type == "SAM3_VideoTrack"][0]
    assert "MieNodes" in sam3.package


# --- to_markdown ---

def test_to_markdown_healthy():
    with patch("app.health_check.requests") as mock_req:
        mock_req.ConnectionError = Exception
        mock_req.Timeout = Exception
        all_files = {m["filename"] for m in health_check.load_requirements()["models"]}
        obj = _object_info_with_models(all_files)
        # 注册所有自定义节点
        for n in health_check.load_requirements()["custom_nodes"]:
            obj[n["class_type"]] = {"input": {"required": {}}}
        mock_req.get.side_effect = [_mock_resp(200, SYSTEM_STATS_OK), _mock_resp(200, obj)]
        report = health_check.check_health("http://127.0.0.1:8188")
    md = report.to_markdown()
    assert "✅" in md  # 连通性 OK
    assert "RTX 4090" in md
    assert report.overall_ok is True


def test_to_markdown_unreachable():
    import requests as real_req
    with patch("app.health_check.requests") as mock_req:
        mock_req.ConnectionError = real_req.ConnectionError
        mock_req.Timeout = real_req.Timeout
        mock_req.get.side_effect = real_req.ConnectionError("refused")
        report = health_check.check_health("http://127.0.0.1:8188")
    md = report.to_markdown()
    assert "❌" in md
    assert "监听" in md or "启动" in md  # 可操作诊断
    assert report.overall_ok is False
