"""图像 runner 应按 definition 的 node_id + field patch 提示词。"""
from app.services import runner


def test_krea2_text_value_field_is_patched(monkeypatch):
    captured = {}
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda name: {"19": {"inputs": {"value": "old"}}})
    monkeypatch.setattr(runner.scail2_client, "build_node_title_map", lambda wf: {})

    def fake_patch(workflow, replacements, **kwargs):
        captured.update(replacements)
        return workflow

    monkeypatch.setattr(runner.scail2_client, "patch_workflow", fake_patch)
    monkeypatch.setattr(runner.scail2_client, "queue_prompt", lambda wf: ("pid", "cid"))
    monkeypatch.setattr(runner.scail2_client, "start_progress_listener", lambda cid: type("Q", (), {"put": lambda self, value: None})())
    monkeypatch.setattr(runner.scail2_client, "wait_for_completion", lambda *args, **kwargs: iter(["✅ done in 00:01"]))
    monkeypatch.setattr(runner.scail2_client, "get_history", lambda pid: {})
    monkeypatch.setattr(runner.scail2_client, "extract_all_image_outputs", lambda hist: [])
    monkeypatch.setattr(runner.history, "write_manifest", lambda manifest: None)

    list(runner.run_image_workflow(
        "t2i_krea2", "a red sports car in rain", ["1024x1024"], False, 77
    ))

    assert captured["19"] == {"value": "a red sports car in rain"}
    assert captured["6"] == {"width": 1024, "height": 1024, "batch_size": 1}
    assert captured["9"] == {"seed": 77}


def test_stream_events_does_not_stop_at_segment_internal_success(monkeypatch):
    def fake_image_run(name, *values):
        yield "[READY] preparing image gen…", None
        yield "[1/1] ✅ done in 00:01", []
        yield "✅ [1/1] 1024x1024 done", ["http://comfy/view?filename=new.png&type=output"]
        yield "✅ 全部完成，共 1 张图", ["http://comfy/view?filename=new.png&type=output"]
    monkeypatch.setattr(runner, "run_image_workflow", fake_image_run)
    monkeypatch.setattr(runner.config, "preset_config", lambda name: {"output_kind": "image", "user_facing_inputs": [{"type": "image_sizes"}]})
    events = list(runner.stream_events("Anima_turbo", ["new prompt"]))
    assert any(e.media_html and "new.png" in e.media_html for e in events)
    assert events[-1].type == "done"
    assert events[-1].state == "success"

def test_failure_message_shows_only_raw_error(monkeypatch):
    """run_image_workflow 失败时, 最终 yield 只显示原始错误全文, 不加分析/前缀.

    用户明确诉求: 错误条只显示原始内容 (能完整复制), 不要 "全部失败" 标题、
    不要 "第 N 个 (共 M 个, WxH)" 位置前缀、不要截断. 这些是用户上一轮反馈
    "不要分析这个内容, 显示原始内容即可" 的直接契约.
    """
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda name: {"3": {}, "6": {}, "9": {}})
    monkeypatch.setattr(runner.scail2_client, "build_node_title_map", lambda wf: {})
    monkeypatch.setattr(runner.scail2_client, "patch_workflow", lambda wf, repl, **kw: wf)
    monkeypatch.setattr(runner.scail2_client, "queue_prompt", lambda wf: ("pid", "cid"))
    monkeypatch.setattr(runner.scail2_client, "start_progress_listener", lambda cid: type("Q", (), {"put": lambda self, value: None})())

    raw_err = "torch.AcceleratorError: CUDA error: no kernel image is available for execution on the device"
    def fake_wait(*args, **kwargs):
        yield f"❌ {raw_err}"
    monkeypatch.setattr(runner.scail2_client, "wait_for_completion", fake_wait)
    monkeypatch.setattr(runner.scail2_client, "get_history", lambda pid: {})
    monkeypatch.setattr(runner.scail2_client, "extract_all_image_outputs", lambda hist: [])
    monkeypatch.setattr(runner.history, "write_manifest", lambda manifest: None)

    # 多尺寸批处理, 第一个失败 -> 整批 abort, 最终提示只含原始错误
    events = list(runner.run_image_workflow(
        "Anima_turbo", "test prompt", ["768x512", "1024x1024", "1280x720"], False, 77
    ))
    final_msg = events[-1][0]
    # 原始错误全文必须在 (不截断, 用户要能完整复制含 NVIDIA 文档链接)
    assert raw_err in final_msg, f"失败提示必须含原始错误全文, 实际 {final_msg!r}"
    # 禁止位置/尺寸前缀 (用户明确说只要原文)
    assert "全部失败" not in final_msg, f"不再加'全部失败'标题, 实际 {final_msg!r}"
    assert "768x512" not in final_msg, f"不再加尺寸前缀, 实际 {final_msg!r}"
    assert "第 1 个" not in final_msg, f"不再加位置前缀, 实际 {final_msg!r}"
    # 禁止截断省略号
    assert "…" not in final_msg, f"不截断, 实际 {final_msg!r}"


def test_failure_status_includes_specific_error_reason(monkeypatch):
    """run_image_workflow 失败时, 最终 yield 必须包含 ComfyUI 的具体错误原因, 不能光说 'failure'.

    现状: final_status='failure' 写了但 final_error 抓到了不展示, 用户看到 '❌ 全部完成，failure 失败于尺寸 1'
    不知道 torch.AcceleratorError / CUDA error 这些关键诊断信息.
    """
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda name: {"3": {}, "6": {}, "9": {}})
    monkeypatch.setattr(runner.scail2_client, "build_node_title_map", lambda wf: {})
    monkeypatch.setattr(runner.scail2_client, "patch_workflow", lambda wf, repl, **kw: wf)
    monkeypatch.setattr(runner.scail2_client, "queue_prompt", lambda wf: ("pid", "cid"))
    monkeypatch.setattr(runner.scail2_client, "start_progress_listener", lambda cid: type("Q", (), {"put": lambda self, value: None})())

    cuda_err = "torch.AcceleratorError: CUDA error: no kernel image is available for execution on the device"

    def fake_wait(*args, **kwargs):
        yield f"❌ {cuda_err}"
    monkeypatch.setattr(runner.scail2_client, "wait_for_completion", fake_wait)
    monkeypatch.setattr(runner.scail2_client, "get_history", lambda pid: {})
    monkeypatch.setattr(runner.scail2_client, "extract_all_image_outputs", lambda hist: [])
    monkeypatch.setattr(runner.scail2_client, "status_svc" if False else "wait_for_completion", fake_wait)  # placeholder; real one set below
    monkeypatch.setattr(runner.scail2_client, "get_history", lambda pid: {})
    monkeypatch.setattr(runner.scail2_client, "extract_all_image_outputs", lambda hist: [])
    monkeypatch.setattr(runner.history, "write_manifest", lambda manifest: None)

    events = list(runner.run_image_workflow(
        "Anima_turbo", "test prompt", ["1024x1024"], False, 77
    ))
    final_msg = events[-1][0]
    assert cuda_err in final_msg, (
        f"失败最终提示必须含 ComfyUI 原始错误, 实际 {final_msg!r}"
    )


def test_timeout_status_uses_distinct_title(monkeypatch):
    """run_image_workflow 超时也不应继续叫 '全部完成'."""
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda name: {"3": {}, "6": {}, "9": {}})
    monkeypatch.setattr(runner.scail2_client, "build_node_title_map", lambda wf: {})
    monkeypatch.setattr(runner.scail2_client, "patch_workflow", lambda wf, repl, **kw: wf)
    monkeypatch.setattr(runner.scail2_client, "queue_prompt", lambda wf: ("pid", "cid"))
    monkeypatch.setattr(runner.scail2_client, "start_progress_listener", lambda cid: type("Q", (), {"put": lambda self, value: None})())

    def fake_wait(*args, **kwargs):
        yield "⏰ 超时: 60s 内未完成"
    monkeypatch.setattr(runner.scail2_client, "wait_for_completion", fake_wait)
    monkeypatch.setattr(runner.scail2_client, "get_history", lambda pid: {})
    monkeypatch.setattr(runner.scail2_client, "extract_all_image_outputs", lambda hist: [])
    monkeypatch.setattr(runner.history, "write_manifest", lambda manifest: None)

    events = list(runner.run_image_workflow(
        "Anima_turbo", "test prompt", ["1024x1024"], False, 77
    ))
    final_msg = events[-1][0]
    assert "全部完成" not in final_msg, f"超时也不应说'全部完成', 实际 {final_msg!r}"
    assert "⏰" in final_msg or "超时" in final_msg, (
        f"超时最终提示应标记超时, 实际 {final_msg!r}"
    )
