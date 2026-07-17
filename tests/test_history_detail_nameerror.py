"""Regression lock: _make_detail_from_run must not NameError on output_kind.

P0-1 (demo.load on history tab) exposed a long-standing bug: the helper
references `output_kind` as a closure variable but it was never defined in
the function's scope. Before demo.load, only manual button clicks reached
this path, so the bug stayed latent. With auto-load at startup, every fresh
session trips it.

Contract: calling _make_detail_from_run with a run that has `output` set
must return a 4-tuple where media_html contains <img>/<video>/<audio> based
on the run's preset's output_kind (image/video/audio). No NameError.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import scail2_app, config


def _make_run(preset_name: str, output_filename: str):
    return {
        "preset": preset_name,
        "status": "success",
        "prompt_id": "test-prompt-001",
        "created_at": "2026-07-17T07:00:00+00:00",
        "finished_at": "2026-07-17T07:01:00+00:00",
        "duration_sec": 60,
        "cache_hit": False,
        "prompt": "test prompt",
        "output": {
            "filename": output_filename,
            "subfolder": "",
            "type": "output",
        },
    }


def test_make_detail_image_run_no_nameerror():
    """Image preset (zimage) run should not NameError -- P0-1 startup load hits this path."""
    run = _make_run("zimage", "z_00001_.png")
    summary, media, json_str, prompt_md = scail2_app._make_detail_from_run(run)
    assert "<img" in media, f"image run should render <img>, got: {media!r}"


def test_make_detail_video_run_no_nameerror():
    """Video preset (sca12_motion) run should not NameError and should render <video>."""
    run = _make_run("sca12_motion", "sca12_00001.mp4")
    summary, media, json_str, prompt_md = scail2_app._make_detail_from_run(run)
    assert "<video" in media, f"video run should render <video>, got: {media!r}"


def test_make_detail_audio_run_no_nameerror():
    """Audio preset (qwen3_tts) run should not NameError and should render <audio>."""
    run = _make_run("qwen3_tts", "qwen3_00001.wav")
    summary, media, json_str, prompt_md = scail2_app._make_detail_from_run(run)
    assert "<audio" in media, f"audio run should render <audio>, got: {media!r}"


def test_make_detail_no_run_returns_empty():
    """Empty run must still return the 4-tuple empty placeholders (existing contract)."""
    summary, media, json_str, prompt_md = scail2_app._make_detail_from_run(None)
    assert "选中一条记录查看详情" in summary
    assert json_str == ""
    assert prompt_md == ""
