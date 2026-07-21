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
    assert len(flat) == len(specs), (
        f"sca12_motion flat 长度 {len(flat)} != specs {len(specs)}"
    )

    # spec[4] file:video -> 必须存在且是 gr.File 而不是 gr.Number
    assert isinstance(flat[4], gr.File), (
        f"spec[4] (469 file:video) 应是 gr.File, 实际 {type(flat[4]).__name__}"
    )
    # spec[5] int frame_load_cap -> 必须存在且是 gr.Number
    assert isinstance(flat[5], gr.Number), (
        f"spec[5] (469 int frame_load_cap) 应是 gr.Number, 实际 {type(flat[5]).__name__}"
    )
    # 同一个 node 上的两个 component 必须是不同的对象 (旧 dict 实现会丢前一个)
    assert id(flat[4]) != id(flat[5]), (
        "spec[4] 与 spec[5] 必须是不同 component 对象 (旧 dict-by-node_id 会重复)"
    )

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


def test_render_form_sca12_replace_one_component_per_spec():
    """sca12_replace 现在跟 sca12_motion 共用 schema (驱动在 469 同时挂 video + int),
    8 个 spec -> 8 个 flat component, 不能因为 dict-by-node_id 丢 component。

    回归锁: flat[i] 对应 specs[i] (按 spec 顺序), 不因同 node 重复写而错位。
    """
    cfg = config.preset_config("sca12_replace")
    specs = cfg["user_facing_inputs"]
    with gr.Blocks():
        flat = scail2_app._render_workflow_form("sca12_replace")
    assert len(flat) == len(specs), (
        f"sca12_replace flat 长度 {len(flat)} != specs {len(specs)}"
    )
    file_spec_idx = next(i for i, s in enumerate(specs) if s.get("type") == "file:video")
    int_spec_idx = next(
        i for i, s in enumerate(specs)
        if s.get("type") == "int" and str(s["node_id"]) == "469"
    )
    assert isinstance(flat[file_spec_idx], gr.File), (
        f"sca12_replace spec[{file_spec_idx}] (file:video) 应是 gr.File, 实际 {type(flat[file_spec_idx]).__name__}"
    )
    assert isinstance(flat[int_spec_idx], gr.Number), (
        f"sca12_replace spec[{int_spec_idx}] (int) 应是 gr.Number, 实际 {type(flat[int_spec_idx]).__name__}"
    )
    assert id(flat[file_spec_idx]) != id(flat[int_spec_idx]), (
        "sca12_replace file:video 和 int 两个 469 spec 必须是不同 component 对象"
    )


def test_file_preview_is_populated_when_example_loads(monkeypatch):
    """file:image / file:video 旁路缩略图必须在加载示例后自动更新。

    bug 故事 (review 2026-07-13): _create_one_input 在 gr.File 旁边放 gr.Image /
    gr.Video 缩略图,旧实现只通过 comp.change 监听手动上传,ex_btn.click /
    last_btn.click / wf_radio.change 三条路径都没把它纳入 outputs, 用户切到
    Klein / LTX i2v 后看到的就是"将文件拖放至此处"的空白上传框。
    """
    from unittest.mock import patch

    preset = "klein_edit"
    example_cfg = config.preset_config(preset)
    file_specs = [
        s for s in example_cfg["user_facing_inputs"]
        if s.get("type") in ("file:image", "file:video")
    ]
    assert file_specs, "sanity: klein_edit should have file:image spec"

    fake_preview_image = REPO_ROOT / "app" / "static" / "examples" / "klein_edit.png"
    assert fake_preview_image.exists(), "sanity: test fixture should exist"
    monkeypatch.setattr(
        scail2_app, "_resolve_example_file", lambda fn: str(fake_preview_image)
    )

    with patch("app.scail2_app.run_workflow", lambda *args, **kwargs: iter(["stop"])), \
         patch("app.scail2_app._save_last_run"), \
         gr.Blocks() as demo:
        scail2_app._render_workflow_form(preset)

    file_components = [b for b in demo.blocks.values() if isinstance(b, gr.File)]
    image_components = [b for b in demo.blocks.values() if isinstance(b, gr.Image)]
    assert file_components, "klein_edit should expose a gr.File"
    assert image_components, "klein_edit should expose a gr.Image thumbnail"

    ex_btn = next(
        (entry for entry in demo.fns.values()
         if getattr(entry.fn, "__name__", "") == "_on_ex_btn_click"),
        None,
    )
    assert ex_btn is not None, "klein_edit should wire up the load-example button"
    assert any(out is image_components[0] for out in ex_btn.outputs), (
        "ex_btn click must also target the file preview component. "
        f"outputs={[type(o).__name__ for o in ex_btn.outputs]}"
    )


def test_image_file_preview_is_populated_when_example_loads(monkeypatch):
    """LTX i2v (file:image 作为起始帧) 的 gr.Image 缩略图也必须被 ex_btn.click 触发更新。"""
    from unittest.mock import patch

    preset = "ltx_23_i2v_distilled"
    example_cfg = config.preset_config(preset)
    assert any(
        s.get("type") == "file:image" for s in example_cfg["user_facing_inputs"]
    ), "sanity: ltx_23_i2v_distilled should have file:image spec (起始帧)"

    fake_image = REPO_ROOT / "app" / "static" / "examples" / "person.png"
    assert fake_image.exists(), "sanity: test fixture should exist"
    monkeypatch.setattr(
        scail2_app, "_resolve_example_file", lambda fn: str(fake_image)
    )

    with patch("app.scail2_app.run_workflow", lambda *args, **kwargs: iter(["stop"])), \
         patch("app.scail2_app._save_last_run"), \
         gr.Blocks() as demo:
        scail2_app._render_workflow_form(preset)

    image_components = [b for b in demo.blocks.values() if isinstance(b, gr.Image)]
    assert image_components, "ltx_23_i2v_distilled should expose a gr.Image thumbnail"

    ex_btn = next(
        (entry for entry in demo.fns.values()
         if getattr(entry.fn, "__name__", "") == "_on_ex_btn_click"),
        None,
    )
    assert ex_btn is not None
    assert any(out is image_components[0] for out in ex_btn.outputs), (
        "ex_btn click must also target the gr.Image preview component. "
        f"outputs={[type(o).__name__ for o in ex_btn.outputs]}"
    )


def test_file_input_specs_must_have_example_reference():
    """契约 (review 2026-07-13): preset example 必须是完整可跑的, 所有 file spec 都必须有对应引用。

    bug 故事: 之前我只把缩略图组件的 wiring 修了, 但 Klein / LTX i2v 的 example 里
    没填 reference_image, "加载示例" 之后用户看到的还是空文件框 + 占位缩略图,
    整张表单没法反映"按默认参数跑会得到什么"的概念。正确做法是:
      - file:image spec  -> example.reference_image 必须指向真实存在文件
      - file:video spec  -> example.drive_video 必须指向真实存在文件
      - example 跑出来应该 = preview_image / preview_video 看到的资产
    """
    FILE_KEY = {"file:image": "reference_image", "file:video": "drive_video"}
    missing = []
    for wf in config.list_workflows():
        cfg = config.preset_config(wf["name"])
        ex = cfg.get("example") or {}
        specs = cfg.get("user_facing_inputs", [])
        for spec in specs:
            typ = spec.get("type")
            if typ not in FILE_KEY:
                continue
            key = FILE_KEY[typ]
            if not ex.get(key):
                missing.append((wf["name"], typ, key))
                continue
            staged = scail2_app._resolve_example_file(ex.get(key))
            if not staged:
                missing.append((wf["name"], typ, key + " (staged path resolution failed)"))
                continue
            pth = Path(staged)
            if not pth.exists():
                missing.append((wf["name"], typ, key + f" (file not found: {pth})"))
    assert not missing, (
        f"以下 preset 的 example 缺 file 输入引用, 用户点击加载示例看不到示例素材:\n"
        f"{chr(10).join('  ' + n + ' (' + t + ' -> ' + k + ')' for n, t, k in missing)}\n"
        f"修法: 在 params.json 对应 preset 的 example 里加 reference_image / drive_video, 路径用现有资产 (e.g. app/static/examples/person.png)。"
    )
