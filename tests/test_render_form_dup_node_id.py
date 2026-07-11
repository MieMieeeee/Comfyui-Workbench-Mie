"""回归：sca12_motion 同一 node (469) 多 spec (file:video + int frame_load_cap)
各自创建独立 component，确保 flat inputs 索引严格按 spec 顺序对齐。

bug 故事：旧实现用 inputs_by_nid: dict[str, object] 存 component，同一 node 上
spec[5] (int frame_load_cap) 会覆盖 spec[4] (file:video)，导致 _auto_load_example
返回的 drive_video 路径字符串掉到 gr.Number 上 -> TypeError "type str doesn't
define __round__ method"，前端 toast 出 "错误" 红框覆盖整个表单。

回归锁：每个 spec 在 flat 里各自占一个位置，且 component 类型必须和 spec.type 对齐。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest
import gradio as gr

from app import config, scail2_app


# --- 同一 node 上多 spec 各自有独立 component (sca12_motion 469 双重挂载回归) ---


def test_render_form_duplicate_node_id_each_spec_gets_its_own_component():
    """sca12_motion 里 node 469 同时挂 file:video + int (frame_load_cap), 两个 spec
    必须各自有独立 component —— 否则 flat 索引错位, _auto_load_example 返回的
    drive_video 路径字符串掉到 gr.Number 上 -> TypeError "type str doesn't
    define __round__ method".

    回归根因: 旧实现用 inputs_by_nid: dict 存储 component, 同一 node_id 第 2 次
    写入会覆盖前一个。修复后改用 spec-indexed list, 每个 spec 各自占一个 flat 位置。
    """
    cfg = config.preset_config("sca12_motion")
    specs = cfg["user_facing_inputs"]
    # 验证 schema 假设: sca12_motion 至少 6 个 spec, 且 spec[4] / spec[5] 都是 node 469
    assert len(specs) >= 6, f"sanity: sca12_motion 应至少有 6 个 spec, 实际 {len(specs)}"
    assert specs[4]["node_id"] == "469" and specs[4]["type"] == "file:video"
    assert specs[5]["node_id"] == "469" and specs[5]["type"] == "int"

    with gr.Blocks():
        flat = scail2_app._render_workflow_form("sca12_motion")

    # flat 长度应等于 spec 数 (int_random 拆 2, 这里 sca12_motion 没有 int_random 所以 1:1)
    assert len(flat) == len(specs),         f"sca12_motion flat 长度 {len(flat)} != specs {len(specs)}"

    # spec[4] file:video -> 必须存在且是 gr.File 而不是 gr.Number
    assert isinstance(flat[4], gr.File),         f"spec[4] (469 file:video) 应是 gr.File, 实际 {type(flat[4]).__name__}"
    # spec[5] int frame_load_cap -> 必须存在且是 gr.Number
    assert isinstance(flat[5], gr.Number),         f"spec[5] (469 int frame_load_cap) 应是 gr.Number, 实际 {type(flat[5]).__name__}"
    # 同一个 node 上的两个 component 必须是不同的对象 (旧 dict 实现会丢前一个)
    assert id(flat[4]) != id(flat[5]),         "spec[4] 与 spec[5] 必须是不同 component 对象 (旧 dict-by-node_id 会重复)"

    # 其它 spec 也要按 type 对齐 (整体回归)
    expected_types = {
        "file:image": gr.File,
        "file:video": gr.File,
        "text": gr.Textbox,
        "int": gr.Number,
        "prompt_pool": gr.Textbox,
    }
    for i, spec in enumerate(specs):
        expect_cls = expected_types.get(spec["type"])
        if expect_cls is None:
            continue  # image_sizes / int_random 走自定义, 不在这测
        assert isinstance(flat[i], expect_cls), (
            f"spec[{i}] ({spec['node_id']}/{spec['field']}/{spec['type']}) "
            f"应是 {expect_cls.__name__}, 实际 {type(flat[i]).__name__}"
        )


def test_render_form_sca12_replace_still_one_component_per_spec():
    """旧 schema (每个 node 仅一个 spec) 仍应工作 —— 防止 spec-indexed 重构回归。

    sca12_replace: 8 个 spec, 8 个不同 node_id, flat 长度 == spec 长度。
    """
    cfg = config.preset_config("sca12_replace")
    specs = cfg["user_facing_inputs"]
    with gr.Blocks():
        flat = scail2_app._render_workflow_form("sca12_replace")
    assert len(flat) == len(specs),         f"sca12_replace flat 长度 {len(flat)} != specs {len(specs)}"
    # 且每个 node_id 都唯一 (无重复)
    seen_ids = set()
    for spec in specs:
        nid = str(spec["node_id"])
        assert nid not in seen_ids, f"sca12_replace spec node_id 重复: {nid}"
        seen_ids.add(nid)
