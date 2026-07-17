"""run_workflow should prefer type=output over type=temp when picking the primary image.

User feedback: "I changed style and got no image" + "single word shouldn't have issue"
Root cause: wordcloud workflow has 5 image output nodes:
  - node 10 PreviewImage -> type=temp (SAM segmented)
  - node 22 MaskPreview+ -> type=temp (inverted mask)
  - node 23 SaveImage    -> type=output (final wordcloud)
  - node 25 PreviewImage -> type=temp (RGBA->RGB intermediate)
  - node 29 PreviewImage -> type=temp (post-upscale wordcloud, empty if transparent_background)

extract_all_image_outputs sorts by node_id, so image_outputs[0] = node 10 (SAM mask).
run_workflow takes image_outputs[0] -> output_box shows the mask, not the wordcloud.
Switching colormap still returns same mask, user reports "style not applied".

Fix: in run_workflow, when output_kind="image", prefer type=output first,
fallback type=temp. Semantically mirrors commit 2113045 for video extraction.

Why not change extract_all_image_outputs: it's also called by run_image_workflow
(Gallery) which needs all images in node-order. Fix in run_workflow's image
selection locally is most surgical.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from unittest.mock import patch
import pytest

from app import scail2_app


# ---- fixtures ----

def _fake_wordcloud_history():
    return {"outputs": {
        "10": {"images": [{"filename": "ComfyUI_temp_tteku_00004_.png", "subfolder": "", "type": "temp"}]},
        "22": {"images": [{"filename": "ComfyUI_temp_omqur_00004_.png", "subfolder": "", "type": "temp"}]},
        "23": {"images": [{"filename": "ComfyUI_00053_.png", "subfolder": "", "type": "output"}]},
        "25": {"images": [{"filename": "ComfyUI_temp_ihanb_00010_.png", "subfolder": "", "type": "temp"}]},
        "29": {"images": [{"filename": "ComfyUI_temp_suskb_00010_.png", "subfolder": "", "type": "temp"}]},
    }}


def _fake_wordcloud_outputs():
    return [
        {"filename": "ComfyUI_temp_tteku_00004_.png", "subfolder": "", "type": "temp"},
        {"filename": "ComfyUI_temp_omqur_00004_.png", "subfolder": "", "type": "temp"},
        {"filename": "ComfyUI_00053_.png", "subfolder": "", "type": "output"},
        {"filename": "ComfyUI_temp_ihanb_00010_.png", "subfolder": "", "type": "temp"},
        {"filename": "ComfyUI_temp_suskb_00010_.png", "subfolder": "", "type": "temp"},
    ]


def _fake_url(f, s="", k="output"):
    return f"http://fake/view?f={f}&t={k}"


def _collect_final_url(gen):
    last_url = None
    for _status, url in gen:
        last_url = url
    return last_url


@pytest.fixture
def patched_wordcloud_client():
    """mock scail2_client calls needed to run a wordcloud end-to-end."""
    with patch.object(scail2_app.scail2_client, "load_workflow_template") as mock_load, \
         patch.object(scail2_app.scail2_client, "queue_prompt", return_value="pid-test"), \
         patch.object(scail2_app.scail2_client, "wait_for_completion",
                      return_value=iter(["\u2705 done"])), \
         patch.object(scail2_app.scail2_client, "get_history", return_value=_fake_wordcloud_history()), \
         patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=_fake_wordcloud_outputs()), \
         patch.object(scail2_app.scail2_client, "get_output_url", side_effect=_fake_url), \
         patch.object(scail2_app.scail2_client, "patch_workflow",
                      side_effect=lambda wf, repl, **kw: wf):
        mock_load.return_value = {
            "1": {"inputs": {"image": "x.png"}, "class_type": "LoadImage"},
            "2": {"inputs": {"text": "x", "colormap": "viridis"}, "class_type": "ComfyWordCloud"},
            "10": {"inputs": {}, "class_type": "PreviewImage"},
            "23": {"inputs": {}, "class_type": "SaveImage"},
        }
        yield


def _wordcloud_form_values():
    return [
        "portrait_model.png",
        "Beauty\nComfyUI\nStyle",
        "viridis",
    ]


# ---- tests ----

def test_run_workflow_image_output_prefers_type_output(patched_wordcloud_client):
    url = _collect_final_url(scail2_app.run_workflow("wordcloud", *_wordcloud_form_values()))
    assert url is not None, "expected non-None final url after successful run"
    assert "ComfyUI_00053_.png" in url, (
        f"expected the actual wordcloud image (node 23 type=output), "
        f"got URL={url!r}"
    )
    assert "type=temp" not in url, (
        f"got type=temp image URL (likely SAM mask), got URL={url!r}"
    )


def test_run_workflow_image_output_handles_only_temp(patched_wordcloud_client):
    only_temp = [
        {"filename": "ComfyUI_temp_xxxx_00001_.png", "subfolder": "", "type": "temp"},
    ]
    with patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=only_temp):
        url = _collect_final_url(scail2_app.run_workflow("wordcloud", *_wordcloud_form_values()))
    assert url is not None
    assert "ComfyUI_temp_xxxx_00001_.png" in url


def test_run_workflow_image_output_handles_empty(patched_wordcloud_client):
    with patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=[]):
        url = _collect_final_url(scail2_app.run_workflow("wordcloud", *_wordcloud_form_values()))
    assert url is None


def test_run_workflow_image_output_no_regression_for_single_output_workflow(patched_wordcloud_client):
    single_output = [
        {"filename": "zimage_00001_.png", "subfolder": "", "type": "output"},
    ]
    with patch.object(scail2_app.scail2_client, "extract_all_image_outputs",
                      return_value=single_output):
        url = _collect_final_url(scail2_app.run_workflow("wordcloud", *_wordcloud_form_values()))
    assert url is not None
    assert "zimage_00001_.png" in url
