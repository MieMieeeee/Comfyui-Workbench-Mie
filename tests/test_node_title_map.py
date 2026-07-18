"""node_id -> title 映射测试 (P1: 消 node 号泄漏到 UI)。

覆盖：
- build_node_title_map 从 workflow JSON 抽 _meta.title / class_type / node_id 三级回退
- _last_executed_node 有 title_map 时返回 title, 无 map 时保持现状 "node {id}"

为什么：AGENTS.md "Never leak node numbers into UI copy"。当前 _last_executed_node
直接返回 "node 367" 拼进 status_bar, 用户看到无意义的节点号。workflow JSON 每个
节点都带 _meta.title (KSampler / SamplerCustom / Load Image / Video Combine ...),
patch_workflow 深拷贝时保留 _meta, 所以 patched workflow 仍是 title 的权威来源。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import scail2_client


# --- build_node_title_map ---

def test_build_node_title_map_extracts_meta_title():
    """_meta.title 存在时优先取它 (最人类可读)。"""
    wf = {
        "3": {"inputs": {"seed": 1}, "class_type": "KSampler",
              "_meta": {"title": "KSampler"}},
        "9": {"inputs": {}, "class_type": "SaveImage",
              "_meta": {"title": "Save Image"}},
    }
    m = scail2_client.build_node_title_map(wf)
    assert m["3"] == "KSampler"
    assert m["9"] == "Save Image"


def test_build_node_title_map_falls_back_to_class_type():
    """节点无 _meta 时回退 class_type (ComfyUI 内置类型名, 仍比 node_id 可读)。"""
    wf = {
        "7": {"inputs": {}, "class_type": "CLIPTextEncode"},
    }
    m = scail2_client.build_node_title_map(wf)
    assert m["7"] == "CLIPTextEncode"


def test_build_node_title_map_falls_back_to_node_id():
    """_meta / class_type 都缺的退化节点 -> 回退到 node_id 本身 (不能 None/空串,
    否则 status_bar 显示空白)。"""
    wf = {"11": {"inputs": {}}}
    m = scail2_client.build_node_title_map(wf)
    assert m["11"] == "11"


def test_build_node_title_map_empty_title_falls_back():
    """_meta.title 是空串 -> 视为缺失, 走 class_type 回退。
    (ComfyUI 偶尔导出 title="" 的节点, 空串显示无意义。)"""
    wf = {"5": {"inputs": {}, "class_type": "VAEDecode",
                "_meta": {"title": ""}}}
    m = scail2_client.build_node_title_map(wf)
    assert m["5"] == "VAEDecode"


def test_build_node_title_map_empty_workflow():
    """空 workflow -> 空 map (不崩)。"""
    assert scail2_client.build_node_title_map({}) == {}


# --- _last_executed_node with title_map ---

def test_last_executed_node_uses_title_when_map_given():
    """传 title_map 时, "executing" 消息里的 node_id 被解析成 title。
    这是 P1 的核心: 状态条显示 "KSampler" 而不是 "node 367"。"""
    hist = {"status": {"messages": [["executing", "367"]]}}
    title_map = {"367": "KSampler"}
    assert scail2_client._last_executed_node(hist, title_map=title_map) == "KSampler"


def test_last_executed_node_map_miss_falls_back_to_id():
    """title_map 里没有这个 node_id -> 回退到 node_id 本身 (不带 "node " 前缀,
    因为传了 map 说明调用方想看 title; 缺失就显示原始 id)。
    仍优于 "node 367" (少一个无意义的 "node " 前缀)。"""
    hist = {"status": {"messages": [["executing", "999"]]}}
    title_map = {"367": "KSampler"}
    # map 缺失时: 直接显示 id ("999"), 而不是 "node 999"
    assert scail2_client._last_executed_node(hist, title_map=title_map) == "999"


def test_last_executed_node_preserves_old_behavior_without_map():
    """不传 title_map 时完全保持现状 -> "node 367"。
    向后兼容锁: 所有现有调用方 / 测试 (不传 map) 行为不变。"""
    hist = {"status": {"messages": [["executing", "367"]]}}
    assert scail2_client._last_executed_node(hist) == "node 367"


def test_last_executed_node_no_executing_message():
    """messages 里没有 executing -> None (无论是否传 map)。"""
    hist = {"status": {"messages": [["execution_start", {}]]}}
    assert scail2_client._last_executed_node(hist, title_map={"1": "X"}) is None
