"""run_workflow should prefer type=output over type=temp when picking the primary image.

Generic test: validates the image-output selection chokepoint in run_workflow for
output_kind=="image". Mirrors commit 2113045 / f5bee57 for the video side
(extract_primary_video_output). Behavior tested with a synthetic preset_cfg
(do NOT depend on any real workflow existing -- these tests must work even
when the workflow that originally surfaced the bug is removed).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from unittest.mock import MagicMock, patch
import pytest

from app import scail2_app


# ---- fixtures ----

def _mixed_outputs():
    """5 image outputs: 4 type=temp (intermediate), 1 type=output (final).

    Sorted by node_id ascending; image_outputs[0] is a type=temp SAM-like mask,
    so without the prefer-type=output filter run_workflow picks the wrong one.
    """
    return [
        {"filename": "ComfyUI_temp_mask.png", "subfolder": "", "type": "temp"},
        {"filename": "ComfyUI_temp_invmask.png", "subfolder": "", "type": "temp"},
        {"filename": "ComfyUI_00053_.png", "subfolder": "", "type": "output"},
        {"filename": "ComfyUI_temp_blend.png", "subfolder": "", "type": "temp"},
        {"filename": "ComfyUI_temp_upscale.png", "subfolder": "", "type": "temp"},
    ]


def _mixed_history():
    return {"outputs": {
        "10": {"images": [_mixed_outputs()[0]]},
        "22": {"images": [_mixed_outputs()[1]]},
        "23": {"images": [_mixed_outputs()[2]]},
        "25": {"images": [_mixed_outputs()[3]]},
        "29": {"images": [_mixed_outputs()[4]]},
    }}


def _fake_url(f, s="", k="output"):
    return f"http://fake/view?f={f}&t={k}"


def _collect_final_url(gen):
    last_url = None
    for _status, url in gen:
        last_url = url
    return last_url


def _make_config_mock():
    mock = MagicMock()
    mock.preset_config.return_value = {
        "user_facing_inputs": [
            {"node_id": "1", "field": "image", "type": "file:image"},
            {"node_id": "2", "field": "text", "type": "text", "default": "x"},
            {"node_id": "2", "field": "colormap", "type": "select", "default": "viridis"},
        ],
        "output_kind": "image",
    }
    mock.ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
    mock.ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".webm"}
    mock.MAX_IMAGE_MB = 5
    mock.MAX_VIDEO_MB = 200
    mock.DEFAULT_PROMPT_TEXT = "default prompt"
    # COMFY_INPUT_DIR exists + contains portrait_model.png so _resolve_upload_name
    # returns immediately (skips upload).
    mock.COMFY_INPUT_DIR = Path("E:/FF/ComfyUI_Mie_2026_V8.0/ComfyUI/input").resolve()
    return mock


# wait_for_completion must yield a string starting with "\u2705" so run_workflow's
# final-URL-build branch fires (status.startswith("\u2705") is the trigger).
def _make_success_status():
    return iter(["✅ done in 00:21"])


@pytest.fixture
def patched_client():
    mock_cfg = _make_config_mock()
    with patch.object(scail2_app, "config", mock_cfg), \
         patch.object(scail2_app.scail2_client, "load_workflow_template") as mock_load, \
         patch.object(scail2_app.scail2_client, "queue_prompt", return_value=("pid-test", "client-test")), \
         patch.object(scail2_app.scail2_client, "wait_for_completion",
                      side_effect=lambda *a, **kw: _make_success_status()), \
         patch.object(scail2_app.scail2_client, "get_history", return_value=_mixed_history()), \
         patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=_mixed_outputs()), \
         patch.object(scail2_app.scail2_client, "get_output_url", side_effect=_fake_url), \
         patch.object(scail2_app.scail2_client, "patch_workflow",
                      side_effect=lambda wf, repl, **kw: wf), \
         patch.object(scail2_app.scail2_client, "start_progress_listener",
                      return_value=__import__("queue").Queue()):
        mock_load.return_value = {
            "1": {"inputs": {"image": "x.png"}, "class_type": "LoadImage"},
            "2": {"inputs": {"text": "x", "colormap": "viridis"}, "class_type": "ComfyWC"},
            "10": {"inputs": {}, "class_type": "PreviewImage"},
            "23": {"inputs": {}, "class_type": "SaveImage"},
        }
        yield


def _form_values():
    return [
        "portrait_model.png",
        "Beauty\nComfyUI\nStyle",
        "viridis",
    ]


# ---- tests ----

def test_run_workflow_image_output_prefers_type_output(patched_client):
    """run_workflow should pick the type=output image (final), not type=temp (intermediate)."""
    url = _collect_final_url(scail2_app.run_workflow("synthetic", *_form_values()))
    assert url is not None, "expected non-None final url after successful run"
    assert "ComfyUI_00053_.png" in url, (
        f"expected the final type=output image, got URL={url!r}"
    )
    assert "type=temp" not in url, (
        f"got type=temp image URL (intermediate), got URL={url!r}"
    )


def test_run_workflow_image_output_handles_only_temp(patched_client):
    """Fallback: if workflow only emits type=temp, image_outputs[0] is used."""
    only_temp = [
        {"filename": "ComfyUI_temp_xxxx_00001_.png", "subfolder": "", "type": "temp"},
    ]
    with patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=only_temp):
        url = _collect_final_url(scail2_app.run_workflow("synthetic", *_form_values()))
    assert url is not None
    assert "ComfyUI_temp_xxxx_00001_.png" in url


def test_run_workflow_image_output_handles_empty(patched_client):
    """Empty outputs => URL is None, no crash."""
    with patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=[]):
        url = _collect_final_url(scail2_app.run_workflow("synthetic", *_form_values()))
    assert url is None


def test_run_workflow_image_output_no_regression_for_single_output_workflow(patched_client):
    """Regression: single type=output workflow (e.g. zimage SaveImage only) still works."""
    single_output = [
        {"filename": "zimage_00001_.png", "subfolder": "", "type": "output"},
    ]
    with patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=single_output):
        url = _collect_final_url(scail2_app.run_workflow("synthetic", *_form_values()))
    assert url is not None
    assert "zimage_00001_.png" in url
