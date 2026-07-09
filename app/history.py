"""历史记录 — 扫 app/data/runs/*.json 拿所有 run manifest。

Phase 3 任务（PLAN.md 3.0 / 3.1）。Phase 1 / 2 跑完的 task 也写 manifest。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import config


# prompt_id 是 uuid 格式（含 -），但保险起见过滤一遍文件名
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_\-]")


def _safe_filename(prompt_id: str) -> str:
    return _SAFE_ID_RE.sub("", prompt_id)


# --- 读 ---

def list_runs(
    limit: int | None = None,
    preset: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """按 created_at 倒排读所有 manifest。

    Args:
        limit: 限制返回数量，None = 全部
        preset: 过滤某个 preset。None 或 "全部" 不过滤。
        status: 过滤某种状态(success / failure / timeout)。None 或 "全部" 不过滤。

    Returns:
        list of manifest dict；如果 RUNS_DIR 不存在或为空，返回 []
    """
    if not config.RUNS_DIR.exists():
        return []
    runs: list[dict[str, Any]] = []
    for p in config.RUNS_DIR.glob("*.json"):
        try:
            with p.open("r", encoding="utf-8") as f:
                runs.append(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            # 单个文件坏了不影响其他
            print(f"[history] skip broken manifest {p.name}: {e}")
            continue
    if preset and preset != "全部":
        runs = [r for r in runs if r.get("preset") == preset]
    if status and status != "全部":
        runs = [r for r in runs if r.get("status") == status]
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    if limit is not None:
        return runs[:limit]
    return runs


def get_run(prompt_id: str) -> dict[str, Any] | None:
    """读单个 manifest。"""
    p = config.RUNS_DIR / f"{_safe_filename(prompt_id)}.json"
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def make_view_url(filename: str, subfolder: str = "", kind: str = "output") -> str:
    """拼 /view URL（给历史 tab 用）。走运行时 base url，与 client 保持一致。"""
    from .scail2_client import get_base_url
    qs = f"filename={quote(filename)}&type={kind}&subfolder={quote(subfolder)}"
    return f"{get_base_url()}/view?{qs}"


# --- 写 ---

def write_manifest(manifest: dict[str, Any]) -> Path:
    """写一份 manifest 落盘。

    Required keys in manifest: prompt_id, created_at
    其他字段（preset/reference_image/...）可选。
    """
    if "prompt_id" not in manifest:
        raise ValueError("manifest missing required field: prompt_id")
    if "created_at" not in manifest:
        raise ValueError("manifest missing required field: created_at")

    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = _safe_filename(manifest["prompt_id"])
    out = config.RUNS_DIR / f"{safe_id}.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return out


# --- 辅助：构造 manifest（在 scail2_app.run_workflow 里用） ---

def build_manifest(
    *,
    prompt_id: str,
    started_at_iso: str,
    finished_at_iso: str,
    duration_sec: int,
    preset: str,
    reference_image: str,
    drive_video: str,
    prompt_text: str,
    frames_per_segment: int | None = None,
    pre_drop_frames: int | None = None,
    video_frames: int | None = None,
    max_segments: int | None = None,
    estimated_segments: int | None = None,
    status: str,
    cache_hit: bool = False,
    output: dict[str, str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """组装一份 manifest 字典（不写盘）。"""
    return {
        "prompt_id": prompt_id,
        "created_at": started_at_iso,
        "finished_at": finished_at_iso,
        "duration_sec": duration_sec,
        "preset": preset,
        "reference_image": reference_image,
        "drive_video": drive_video,
        "prompt_text": prompt_text,
        "frames_per_segment": frames_per_segment,
        "pre_drop_frames": pre_drop_frames,
        "video_frames": video_frames,
        "max_segments": max_segments,
        "estimated_segments": estimated_segments,
        "status": status,
        "cache_hit": cache_hit,
        "output": output,
        "error": error,
    }