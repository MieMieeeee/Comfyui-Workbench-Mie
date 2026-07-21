"""端到端 smoke test：上传 + 入队 + 轮询，验证 ComfyUI HTTP 契约通。

需要：
- ComfyUI 在 8188 端口运行
- {COMFY_INSTALL_DIR}/input/halfbody.png 存在
- {COMFY_INSTALL_DIR}/input/buqiwutuan-cut_00001-audio.mp4 存在（驱动视频）

目标：验证契约通，**不**要求完美生成视频。
驱动视频用 1 段（int_range_end=1），跑会很快。

用法：
    py tests/integration_smoke_client.py

退出码：
    0 = 契约通
    1 = 校验失败
    2 = 缺前置文件
    3 = API 失败
    4 = ComfyUI 没起
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import config
from app import scail2_client
from app.workflow_validator import validate, WorkflowValidationError


REF_IMAGE = config.COMFY_INPUT_DIR / "halfbody.png"
# smoke 用的驱动视频：挑一个小的真存在的 mp4 避免 ComfyUI 在 queue 阶段就拒
DRIVE_VIDEO = config.COMFY_INPUT_DIR / "buqiwutuan-cut_00001-audio.mp4"
PRESET = "sca12_replace"


def main() -> int:
    print("=" * 60)
    print("integration smoke client")
    print("=" * 60)
    print(f"COMFY_BASE_URL = {config.COMFY_BASE_URL}")
    print(f"COMFY_INPUT    = {config.COMFY_INPUT_DIR}")
    print(f"REF_IMAGE      = {REF_IMAGE}")
    print(f"DRIVE_VIDEO    = {DRIVE_VIDEO}")
    print(f"PRESET         = {PRESET}")
    print()

    # --- 0. 探活：ComfyUI 8188 端口在不在 ---
    print("[0/5] probing ComfyUI at", config.COMFY_BASE_URL)
    try:
        import requests
        r = requests.get(config.COMFY_BASE_URL + "/system_stats", timeout=5)
        print(f"  /system_stats -> HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"  unexpected status, body: {r.text[:200]}")
            return 4
    except requests.ConnectionError as e:
        print(f"  FAIL: cannot connect to ComfyUI: {e}")
        print("  -> 启动 ComfyUI 启动器.exe 等 :8188 起")
        return 4
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 4

    # --- 1. 加载 + validate workflow ---
    print(f"\n[1/5] loading + validating preset: {PRESET}")
    workflow = scail2_client.load_workflow_template(PRESET)
    preset_cfg = config.preset_config(PRESET)
    try:
        validate(workflow, preset_cfg)
        print(f"  OK: {len(workflow)} nodes, 4 user_facing 节点 + 4 字段 + >=1 video output 全在")
    except WorkflowValidationError as e:
        print(f"  FAIL: {e}")
        return 1

    # --- 2. 上传参考图 + 驱动视频 ---
    print(f"\n[2/5] uploading reference image + drive video")
    if not REF_IMAGE.exists():
        print(f"  FAIL: ref image not found: {REF_IMAGE}")
        return 2
    if not DRIVE_VIDEO.exists():
        print(f"  FAIL: drive video not found: {DRIVE_VIDEO}")
        return 2
    try:
        ref_result = scail2_client.upload(REF_IMAGE, kind="image")
        print(f"  ref image uploaded: {ref_result}")
        ref_name = ref_result["name"]
        drive_result = scail2_client.upload(DRIVE_VIDEO, kind="file")
        print(f"  drive video uploaded: {drive_result}")
        drive_name = drive_result["name"]
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 3

    # --- 3. patch workflow ---
    print(f"\n[3/5] patching workflow")
    patched = scail2_client.patch_workflow(
        workflow,
        replacements={
            "30":  {"image": ref_name},
            "369": {"video": drive_name},
            "360": {"text": "smoke test prompt"},
            "479": {"int_range_end": 1},
        },
        preset_config=preset_cfg,
        validate_after=True,
    )
    print(f"  OK: 4 处替换 + validate after")

    # --- 4. 入队 ---
    print(f"\n[4/5] queueing prompt")
    try:
        prompt_id = scail2_client.queue_prompt(patched, client_id="smoke-test")
        print(f"  OK: prompt_id = {prompt_id}")
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 3

    # --- 5. 轮询一次 ---
    print(f"\n[5/5] polling /history/{prompt_id[:8]}...")
    time.sleep(3)
    try:
        hist = scail2_client.get_history(prompt_id)
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 3
    if hist is None:
        print(f"  no history yet (ComfyUI 还没开始执行，正常)")
    else:
        status = hist.get("status", {})
        print(f"  status: completed={status.get('completed')}, status_str={status.get('status_str')!r}")
        # 不要求 success — 1 段 81 latent 帧可能时间不够，模型可能还没下完
        # 但要 API 返了 history，契约就通了

    # --- 6. 测一下 extract + get_output_url（不要求真出视频）---
    print(f"\n[+] extract_primary_video_output (空 history 测试)")
    out = scail2_client.extract_primary_video_output(hist or {})
    print(f"  result: {out}")
    if out is None:
        url = scail2_client.get_output_url("scail-2-loop_00001.mp4", "SCAIL-2")
        print(f"  fallback get_output_url example: {url}")

    print()
    print("=" * 60)
    print("SMOKE OK: contract verified")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())