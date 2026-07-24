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
