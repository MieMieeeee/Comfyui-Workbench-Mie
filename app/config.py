"""运行时配置 — 所有路径/端口/阈值都集中在这里。

约定：
- 改路径 → 改这里，不要散落到代码
- 改阈值（max MB、timeout）→ 改这里
- 不要在这里写业务逻辑

环境变量覆盖：所有 *_DIR/*_URL/*_PORT/*_SEC 都接受同名环境变量覆盖。
"""
from __future__ import annotations

import os
from pathlib import Path


# --- 仓库根 ---

REPO_ROOT: Path = Path(__file__).resolve().parent.parent


# --- ComfyUI HTTP 服务 ---

COMFY_BASE_URL: str = os.environ.get("COMFY_BASE_URL", "http://127.0.0.1:8188")


# --- ComfyUI 端文件系统 ---

COMFY_INSTALL_DIR: Path = Path(os.environ.get(
    "COMFY_INSTALL_DIR",
    r"E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI",
))
COMFY_INPUT_DIR: Path = COMFY_INSTALL_DIR / "input"
COMFY_OUTPUT_DIR: Path = COMFY_INSTALL_DIR / "output" / "SCAIL-2"
COMFY_CACHE_DIR: Path = COMFY_INSTALL_DIR / "mie_nodes_cache"


# --- 我们仓库内 ---

PRESETS_DIR: Path = REPO_ROOT / "app" / "presets"
PARAMS_FILE: Path = PRESETS_DIR / "params.json"

# 每次运行的 sidecar manifest 落盘位置（Phase 3 用）
RUNS_DIR: Path = REPO_ROOT / "app" / "data" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# 用户上次跑过的参数记忆（per preset）
# 与 RUNS_DIR 的审计 manifest 互斥：manifest 是 audit 追溯用的
# 完整记录，这里只存“上次跑成功的参数”供一键加载。
LAST_RUN_DIR: Path = REPO_ROOT / "app" / "data" / "last_run"
LAST_RUN_DIR.mkdir(parents=True, exist_ok=True)

# 用户主题选择持久化 —— 跨启动沿用 last picked theme_id
THEME_SETTINGS_FILE: Path = REPO_ROOT / "app" / "data" / "theme_settings.json"
THEME_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)


# --- 输入限制（Phase 1.3 用） ---

MAX_IMAGE_MB: int = 5
MAX_VIDEO_MB: int = 200
MAX_PROMPT_CHARS: int = 2000

ALLOWED_IMAGE_EXT: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})
ALLOWED_VIDEO_EXT: frozenset[str] = frozenset({".mp4", ".mov", ".webm"})

DEFAULT_PROMPT_TEXT: str = "A person walking naturally."


# --- 运行 ---

DEFAULT_TIMEOUT_SEC: int = 30 * 60   # 30 分钟
POLL_INTERVAL_SEC: int = 2


# --- WebUI 服务 (Flask, migrate-to-flask 2026-07-21) ---
# GRADIO_HOST/PORT 保留为别名向后兼容 (老脚本/老 import 仍能读).
# 新代码应该用 FLASK_HOST/PORT 或 WEBUI_HOST/PORT.

FLASK_HOST: str = os.environ.get("FLASK_HOST", os.environ.get("WEBUI_HOST", "0.0.0.0"))
FLASK_PORT: int = int(os.environ.get("FLASK_PORT", os.environ.get("WEBUI_PORT", "8199")))
# 向后兼容别名
GRADIO_HOST = FLASK_HOST
GRADIO_PORT = FLASK_PORT


# --- 辅助函数 ---

def workflow_path(preset_name: str) -> Path:
    """从 preset 名取 workflow JSON 路径。

    优先读 preset 配置里的 `workflow_file` 字段（允许 preset 名跟文件名不同，
    例如 sca12_replace 和 sca12_motion 都用 scail2_motion_transfer_final.json）；
    没有该字段则回退到 {preset_name}.json（向后兼容）。
    """
    try:
        cfg = preset_config(preset_name)
        wf_file = cfg.get("workflow_file")
        if wf_file:
            return PRESETS_DIR / wf_file
    except KeyError:
        pass
    return PRESETS_DIR / f"{preset_name}.json"


def preset_config(preset_name: str) -> dict:
    """从 params.json 取单个 preset 的配置。"""
    import json
    with PARAMS_FILE.open("r", encoding="utf-8") as f:
        all_presets = json.load(f)["presets"]
    if preset_name not in all_presets:
        raise KeyError(f"unknown preset: {preset_name}. known: {list(all_presets)}")
    return all_presets[preset_name]


def list_workflows() -> list[dict]:
    """列出所有 workflow preset，按 order 排序，供 UI 渲染左侧列表。

    每项含：name / display_name / category / description / order。
    缺失字段用默认值兜底，保证调用方拿到统一 schema。
    """
    import json
    with PARAMS_FILE.open("r", encoding="utf-8") as f:
        all_presets = json.load(f)["presets"]
    rows = []
    for name, cfg in all_presets.items():
        rows.append({
            "name": name,
            "display_name": cfg.get("display_name", name),
            "category": cfg.get("category", "other"),
            "description": cfg.get("description", ""),
            "order": cfg.get("order", 999),
        })
    rows.sort(key=lambda r: r["order"])
    return rows


# --- 启动期自检（仅在直接跑这个文件时打印，不在 import 时副作用） ---

if __name__ == "__main__":
    print(f"REPO_ROOT       = {REPO_ROOT}")
    print(f"COMFY_BASE_URL  = {COMFY_BASE_URL}")
    print(f"COMFY_INSTALL   = {COMFY_INSTALL_DIR}")
    print(f"COMFY_INPUT_DIR = {COMFY_INPUT_DIR}")
    print(f"COMFY_OUTPUT    = {COMFY_OUTPUT_DIR}")
    print(f"PRESETS_DIR     = {PRESETS_DIR}")
    print(f"RUNS_DIR        = {RUNS_DIR}")
    print(f"WEBUI           = {FLASK_HOST}:{FLASK_PORT}")