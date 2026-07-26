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
    monkeypatch.setattr(runner.config, "preset_config", lambda name: {"output_kind": "image"})
    events = list(runner.stream_events("Anima_turbo", ["new prompt"]))
    assert any(e.media_html and "new.png" in e.media_html for e in events)
    assert events[-1].type == "done"
    assert events[-1].state == "success"
