"""模型参数类 (services.model_slots) 单测 — 不碰网络.

覆盖:
- LOADER_MAP 覆盖 9 种 loader
- discover_slots 扫图
- extract_options 从 /object_info 取已装列表 (含降级)
- fetch_object_info 缓存 + 失败降级
- slots_for_preset 读 definition model 条目 + 算 installed
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.services import model_slots


# --- LOADER_MAP ---

def test_loader_map_covers_all_known_loaders():
    expected = {
        "CheckpointLoaderSimple", "UNETLoader", "UnetLoaderGGUF", "VAELoader",
        "CLIPLoader", "CLIPVisionLoader", "LoraLoader", "LoraLoaderModelOnly",
        "LatentUpscaleModelLoader",
    }
    assert expected <= set(model_slots.LOADER_MAP.keys())
    for cls, (field, folder, label) in model_slots.LOADER_MAP.items():
        assert field and folder and label, f"{cls} 映射不完整"


# --- discover_slots ---

def test_discover_slots_finds_all_loaders_in_graph():
    graph = {
        "16": {"class_type": "UNETLoader", "inputs": {"unet_name": "Z\\a.safetensors"}},
        "17": {"class_type": "VAELoader", "inputs": {"vae_name": "Flux\\ae.sft"}},
        "99": {"class_type": "KSampler", "inputs": {"seed": 1}},  # 非 loader, 跳过
        "20": {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": "x.safetensors", "strength_model": 1.0}},
    }
    slots = model_slots.discover_slots(graph)
    by_key = {s.key: s for s in slots}
    assert set(by_key) == {"16::unet_name", "17::vae_name", "20::lora_name"}
    assert by_key["16::unet_name"].class_type == "UNETLoader"
    assert by_key["16::unet_name"].required_filename == "Z\\a.safetensors"
    assert by_key["16::unet_name"].label == "扩散模型"
    assert by_key["16::unet_name"].folder == "diffusion_models"


def test_discover_slots_handles_non_dict_and_empty():
    assert model_slots.discover_slots({}) == []
    assert model_slots.discover_slots(None) == []  # type: ignore[arg-type]
    assert model_slots.discover_slots({"1": "not a dict"}) == []  # type: ignore[list-item]


# --- extract_options ---

def _oi(class_type, field, files):
    return {class_type: {"input": {"required": {field: [files, {}]}}}}


def test_extract_options_returns_filename_list():
    oi = _oi("UNETLoader", "unet_name", ["a.safetensors", "b\\c.safetensors"])
    assert model_slots.extract_options(oi, "UNETLoader", "unet_name") == ["a.safetensors", "b\\c.safetensors"]


def test_extract_options_degrades_on_missing():
    assert model_slots.extract_options({}, "UNETLoader", "unet_name") == []
    assert model_slots.extract_options(_oi("X", "f", []), "Y", "f") == []  # class 不在
    assert model_slots.extract_options(_oi("UNETLoader", "unet_name", []), "UNETLoader", "vae_name") == []  # field 不在
    # 形状不对 (不是 [[...], {}])
    bad = {"UNETLoader": {"input": {"required": {"unet_name": "bare string"}}}}
    assert model_slots.extract_options(bad, "UNETLoader", "unet_name") == []


# --- fetch_object_info (缓存 + 降级) ---

class _FakeResp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


def test_fetch_object_info_caches_and_reuses(monkeypatch):
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return _FakeResp(200, {"UNETLoader": {"input": {"required": {}}}})

    monkeypatch.setattr(model_slots.requests, "get", fake_get)
    model_slots._object_info_cache.clear()  # 清缓存, 隔离测试
    base = "http://127.0.0.1:8188"
    d1 = model_slots.fetch_object_info(base)
    d2 = model_slots.fetch_object_info(base)  # 应命中缓存, 不再请求
    assert d1 is d2 and d1 is not None
    assert len(calls) == 1, "第二次应走缓存, 不发请求"


def test_fetch_object_info_returns_none_on_failure(monkeypatch):
    def fake_get(url, timeout=None):
        return _FakeResp(500, {})

    monkeypatch.setattr(model_slots.requests, "get", fake_get)
    model_slots._object_info_cache.clear()
    assert model_slots.fetch_object_info("http://x:8188") is None

    def raising(url, timeout=None):
        raise model_slots.requests.ConnectionError("boom")

    monkeypatch.setattr(model_slots.requests, "get", raising)
    assert model_slots.fetch_object_info("http://y:8188") is None  # 网络异常也不抛


def test_fetch_object_info_empty_base_returns_none():
    assert model_slots.fetch_object_info("") is None
    assert model_slots.fetch_object_info(None) is None  # type: ignore[arg-type]


# --- slots_for_preset ---

def test_slots_for_preset_builds_views(monkeypatch):
    cfg = {"user_facing_inputs": [
        {"node_id": "16", "field": "unet_name", "type": "model", "tier": "model",
         "default": "Z\\a.safetensors"},
        {"node_id": "6", "field": "text", "type": "text", "tier": "basic"},  # 非 model, 跳过
    ]}
    graph = {"16": {"class_type": "UNETLoader", "inputs": {"unet_name": "Z\\a.safetensors"}}}

    monkeypatch.setattr(model_slots.config, "preset_config", lambda n: cfg)
    monkeypatch.setattr(model_slots, "_load_graph", lambda n: graph)
    monkeypatch.setattr(model_slots, "fetch_object_info",
                        lambda base, timeout=8, force=False: {"UNETLoader": {"input": {"required": {"unet_name": [["Z\\a.safetensors", "Z\\b.safetensors"], {}]}}}})

    slots, fetched = model_slots.slots_for_preset("zimage")
    assert fetched is True
    assert len(slots) == 1
    s = slots[0]
    assert s.key == "16::unet_name"
    assert s.class_type == "UNETLoader"
    assert s.required_filename == "Z\\a.safetensors"
    assert s.installed is True  # required 在 available 里
    assert "Z\\b.safetensors" in s.available


def test_slots_for_preset_marks_missing_when_not_installed(monkeypatch):
    cfg = {"user_facing_inputs": [
        {"node_id": "16", "field": "unet_name", "type": "model", "default": "MISSING.safetensors"},
    ]}
    graph = {"16": {"class_type": "UNETLoader", "inputs": {"unet_name": "MISSING.safetensors"}}}
    monkeypatch.setattr(model_slots.config, "preset_config", lambda n: cfg)
    monkeypatch.setattr(model_slots, "_load_graph", lambda n: graph)
    monkeypatch.setattr(model_slots, "fetch_object_info",
                        lambda base, timeout=8, force=False: {"UNETLoader": {"input": {"required": {"unet_name": [["other.safetensors"], {}]}}}})
    slots, _ = model_slots.slots_for_preset("zimage")
    assert slots[0].installed is False
    assert slots[0].required_filename == "MISSING.safetensors"


def test_slots_for_preset_offline_returns_empty_available(monkeypatch):
    """ComfyUI 离线: fetch_object_info=None → fetched=False, available=[], 但 slots 仍返回."""
    cfg = {"user_facing_inputs": [
        {"node_id": "16", "field": "unet_name", "type": "model", "default": "a.safetensors"},
    ]}
    graph = {"16": {"class_type": "UNETLoader", "inputs": {"unet_name": "a.safetensors"}}}
    monkeypatch.setattr(model_slots.config, "preset_config", lambda n: cfg)
    monkeypatch.setattr(model_slots, "_load_graph", lambda n: graph)
    monkeypatch.setattr(model_slots, "fetch_object_info", lambda base, timeout=8, force=False: None)
    slots, fetched = model_slots.slots_for_preset("zimage")
    assert fetched is False
    assert slots[0].available == []
    assert slots[0].installed is False  # 离线无法判定已装
    assert slots[0].required_filename == "a.safetensors"  # 清单仍能显示
