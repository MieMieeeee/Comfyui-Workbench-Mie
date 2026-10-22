"""表单值 → 节点字段的槽位对齐 (issue #1 回归).

背景: run_image_workflow 的解析循环曾经把「spec 索引」和「扁平表单值索引」当成同一个
计数器 —— int_random 占 2 格时 i += 2, 紧跟其后的那个 spec 被整个跳过, 后面所有字段
的值都往前错一格. 表现: Z-Image-Turbo 的 VAELoader 收到 unet 的文件名, CLIPLoader 收到
vae 的文件名, ComfyUI 直接 400 (queue_prompt failed: prompt_outputs_failed_validation).

锁: 扁平表单值数组里每一格必须落到它自己那个 spec 的节点/字段上, 一个都不许串位.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import config
from app.services import form_schema, runner


def _patch_capture(monkeypatch, captured):
    """mock scail2_client: 抓 replacements, 其余打桩 (同 test_runner_model.py)."""
    monkeypatch.setattr(runner.scail2_client, "patch_workflow",
                        lambda wf, replacements, **kwargs: captured.update(replacements) or wf)
    monkeypatch.setattr(runner.scail2_client, "queue_prompt", lambda wf: ("pid", "cid"))
    monkeypatch.setattr(runner.scail2_client, "build_node_title_map", lambda wf: {})
    monkeypatch.setattr(runner.scail2_client, "start_progress_listener",
                        lambda cid: type("Q", (), {"put": lambda self, value: None})())
    monkeypatch.setattr(runner.scail2_client, "wait_for_completion",
                        lambda *a, **kw: iter(["✅ done"]))
    monkeypatch.setattr(runner.scail2_client, "get_history", lambda pid: {})
    monkeypatch.setattr(runner.scail2_client, "extract_all_image_outputs", lambda hist: [])
    monkeypatch.setattr(runner.scail2_client, "extract_primary_video_output", lambda hist: None)
    monkeypatch.setattr(runner.history, "write_manifest", lambda manifest: None)
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda n: {"nodes": {}})


def test_zimage_models_land_on_their_own_nodes(monkeypatch):
    """zimage: unet/vae/clip 三个模型字段各自落到自己的 loader 节点上."""
    captured = {}
    _patch_capture(monkeypatch, captured)

    values = form_schema.example_to_form_values("zimage")
    list(runner.run_image_workflow("zimage", *values))

    specs = {s["field"]: s for s in config.preset_config("zimage")["user_facing_inputs"]}
    assert captured["16"]["unet_name"] == specs["unet_name"]["default"]
    assert captured["17"]["vae_name"] == specs["vae_name"]["default"]
    assert captured["18"]["clip_name"] == specs["clip_name"]["default"]
    # 串位时最容易出现的两种错位: VAE 拿到 unet 的名字 / CLIP 拿到 VAE 的名字
    assert captured["17"]["vae_name"] != specs["unet_name"]["default"]
    assert captured["18"]["clip_name"] != specs["vae_name"]["default"]


def test_zimage_seed_and_prompt_not_shifted(monkeypatch):
    """zimage: 种子 / 提示词 / 尺寸也没被 int_random 挤掉一格."""
    captured = {}
    _patch_capture(monkeypatch, captured)

    values = form_schema.example_to_form_values("zimage")
    list(runner.run_image_workflow("zimage", *values))

    assert captured["6"]["text"] == values[0]
    assert captured["13"]["width"] == 720 and captured["13"]["height"] == 1280
    assert captured["3"]["seed"] == values[3]


def test_model_override_value_reaches_its_own_node(monkeypatch):
    """用户在模型下拉里换的模型必须落到自己那个节点 (不再串到下一个 loader)."""
    captured = {}
    _patch_capture(monkeypatch, captured)

    values = form_schema.example_to_form_values("zimage")
    # 扁平数组: [prompt, sizes, 随机勾, 种子, unet, vae, clip]
    values[4] = "My\\unet.safetensors"
    values[5] = "My\\vae.safetensors"
    values[6] = "My\\clip.safetensors"
    list(runner.run_image_workflow("zimage", *values))

    assert captured["16"]["unet_name"] == "My\\unet.safetensors"
    assert captured["17"]["vae_name"] == "My\\vae.safetensors"
    assert captured["18"]["clip_name"] == "My\\clip.safetensors"


def test_every_image_preset_with_int_random_keeps_model_slots_aligned(monkeypatch):
    """所有「int_random 后面还有 model 字段」的 image preset 都逐个校验槽位对齐."""
    checked = []
    for row in config.list_workflows():
        name = row["name"]
        cfg = config.preset_config(name)
        if cfg.get("output_kind") != "image":
            continue
        inputs = cfg["user_facing_inputs"]
        types = [s.get("type") for s in inputs]
        if "int_random" not in types or "model" not in types:
            continue
        # 只看走 image 路径 (run_image_workflow) 的 preset —— 路由规则见
        # runner.stream_events: image 输出 + 有 image_sizes + 没有 file 类输入.
        if "image_sizes" not in types or any(t.startswith("file:") for t in types):
            continue
        seed_pos = types.index("int_random")
        model_specs = [s for i, s in enumerate(inputs)
                       if s.get("type") == "model" and i > seed_pos]
        if not model_specs:
            continue  # int_random 在模型字段之后 —— 不触发错位
        captured = {}
        _patch_capture(monkeypatch, captured)
        values = form_schema.example_to_form_values(name)
        list(runner.run_image_workflow(name, *values))
        for spec in model_specs:
            nid, field = str(spec["node_id"]), spec["field"]
            assert captured.get(nid, {}).get(field) == spec["default"], (
                f"{name}: node {nid}.{field} 收到的不是自己的模型值")
        checked.append(name)
    assert checked, "没有 preset 触发这个 case, 测试本身失去意义"
