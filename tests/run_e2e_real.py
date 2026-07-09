"""端到端真跑脚本（不是 smoke，不 mock）。

用 SCAIL-2 真源素材跑一次完整链路，验证：
- 上传参考图 + 驱动视频
- 4 处 patch + 入队
- 完整跑完一轮（5-15 分钟）
- 拿 outputs 拼 /view URL

参数：
- preset: sca12_replace
- 驱动视频: E:/cc/data/scail2/output/remote_run/jiuwanzi_ref.mp4 (568 帧, ~30s)
- 参考图: E:/cc/data/scail2/input/chibi-sailor-blue.png
- 段数: 1
- 提示词: 默认
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


REF_IMAGE = Path(r"E:/cc/data/scail2/input/chibi-sailor-blue.png")
DRIVE_VIDEO = Path(r"E:/cc/data/scail2/output/remote_run/jiuwanzi_ref.mp4")
PRESET = "sca12_replace"
SEGMENTS = 1


def main() -> int:
    print("=" * 60)
    print("end-to-end real run")
    print("=" * 60)
    print(f"ref image  = {REF_IMAGE} ({REF_IMAGE.stat().st_size / 1024:.1f} KB)")
    print(f"drive video= {DRIVE_VIDEO} ({DRIVE_VIDEO.stat().st_size / 1024:.1f} KB)")
    print(f"preset     = {PRESET}")
    print(f"segments   = {SEGMENTS}")
    print()

    # 1. load + validate
    print("[1/5] loading + validating workflow")
    wf = scail2_client.load_workflow_template(PRESET)
    preset_cfg = config.preset_config(PRESET)
    validate(wf, preset_cfg)
    print(f"  OK: {len(wf)} nodes")

    # 2. upload
    print(f"\n[2/5] uploading ref image")
    ref = scail2_client.upload(REF_IMAGE, kind="image")
    print(f"  ref: {ref}")
    print(f"\n[3/5] uploading drive video")
    drive = scail2_client.upload(DRIVE_VIDEO, kind="file")
    print(f"  drive: {drive}")

    # 3. patch
    print(f"\n[4/5] patching workflow")
    patched = scail2_client.patch_workflow(
        wf,
        replacements={
            "30":  {"image": ref["name"]},
            "369": {"video": drive["name"]},
            "360": {"text": "A person walking naturally."},
            "479": {"int_range_end": SEGMENTS},
        },
        preset_config=preset_cfg,
        validate_after=True,
    )
    print(f"  OK")

    # 4. queue
    print(f"\n[5/5] queueing + waiting for completion")
    prompt_id = scail2_client.queue_prompt(patched, client_id="end-to-end-real")
    print(f"  prompt_id = {prompt_id}")
    print(f"  (this will take 5-15 min, polling every {config.POLL_INTERVAL_SEC}s)")
    print()

    start = time.time()
    for status_msg in scail2_client.wait_for_completion(prompt_id):
        elapsed = int(time.time() - start)
        print(f"  [{elapsed // 60:02d}:{elapsed % 60:02d}] {status_msg}")
        if status_msg.startswith("\u2705"):
            # 拿 outputs
            hist = scail2_client.get_history(prompt_id)
            out = scail2_client.extract_primary_video_output(hist or {})
            if out:
                url = scail2_client.get_output_url(out["filename"], out["subfolder"], out["type"])
                print(f"\n  OUTPUT: {url}")
                print(f"  filename: {out['filename']}")
                print(f"  subfolder: {out['subfolder']}")
            else:
                print(f"\n  no video output in history")
            break
        if status_msg.startswith("\u274c") or status_msg.startswith("\u23f0"):
            break

    print(f"\ntotal time: {(time.time() - start) // 60:.0f}m {(time.time() - start) % 60:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())