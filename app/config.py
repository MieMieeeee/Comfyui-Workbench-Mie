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
# ComfyUI 输出根目录 (不写死 SCAIL-2 子目录 — 不同 preset 输出到不同 subfolder,
# e.g. SCAIL-2 / zzzz / audio / 根目录. "打开输出目录" 开根目录, 用户自己进子目录).
COMFY_OUTPUT_DIR: Path = COMFY_INSTALL_DIR / "output"
COMFY_CACHE_DIR: Path = COMFY_INSTALL_DIR / "mie_nodes_cache"


# --- 我们仓库内 ---

PRESETS_DIR: Path = REPO_ROOT / "app" / "presets"
PARAMS_FILE: Path = PRESETS_DIR / "params.json"
# 每个 preset 一个独立 definition.json (workflow-decouple 2026-07-24).
# preset_config 先读这里, 找不到回退 PARAMS_FILE (迁移期 + 老测试兼容).
# 引导向导 save_definition() 写到这里, 新增工作流不碰 params.json.
DEFINITIONS_DIR: Path = PRESETS_DIR / "definitions"
INPUT_LAYOUTS_DIR: Path = REPO_ROOT / "app" / "data" / "input_layouts"

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
# Gradio 下线后只剩 Flask 入口. 环境变量优先级: FLASK_* > WEBUI_* (老脚本兼容) > 默认值.

FLASK_HOST: str = os.environ.get("FLASK_HOST", os.environ.get("WEBUI_HOST", "0.0.0.0"))
FLASK_PORT: int = int(os.environ.get("FLASK_PORT", os.environ.get("WEBUI_PORT", "8199")))


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
    """读取 definition/params 主配置，再叠加用户输入布局。"""
    import json
    def_path = DEFINITIONS_DIR / f"{preset_name}.json"
    if def_path.exists():
        with def_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
        return _apply_input_layout(preset_name, cfg)
    with PARAMS_FILE.open("r", encoding="utf-8") as f:
        all_presets = json.load(f)["presets"]
    if preset_name not in all_presets:
        raise KeyError(f"unknown preset: {preset_name}. known: {list(all_presets)}")
    return _apply_input_layout(preset_name, all_presets[preset_name])


def _apply_input_layout(preset_name: str, cfg: dict) -> dict:
    """叠加用户输入布局，只修改顺序和显示字段。"""
    import copy
    import json
    path = INPUT_LAYOUTS_DIR / f"{preset_name}.json"
    if not path.exists():
        return cfg
    try:
        layout = json.loads(path.read_text(encoding="utf-8"))
        submitted = layout.get("inputs", [])
        original = cfg.get("user_facing_inputs", [])
        by_id = {f"{x.get('node_id')}::{x.get('field')}": x for x in original}
        ids = [item.get("stable_id") for item in submitted]
        if len(ids) != len(original) or len(set(ids)) != len(ids) or set(ids) != set(by_id):
            return cfg
        merged = []
        for item in submitted:
            spec = copy.deepcopy(by_id[item["stable_id"]])
            for key in ("label", "tier", "help"):
                if isinstance(item.get(key), str):
                    spec[key] = item[key]
            merged.append(spec)
        out = copy.deepcopy(cfg)
        out["user_facing_inputs"] = merged
        return out
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return cfg


def list_workflows() -> list[dict]:
    """列出所有 workflow preset，按 order 排序，供 UI 渲染左侧列表。

    每项含：name / display_name / category / description / order。
    缺失字段用默认值兜底，保证调用方拿到统一 schema。

    双源: 合并 DEFINITIONS_DIR/*.json + PARAMS_FILE.presets, 同名 definition 优先
    (迁移期允许两边都有同名 preset, definition 覆盖 params.json).
    """
    import json
    merged: dict[str, dict] = {}
    # 1. 先读旧源 (params.json), 作为底
    with PARAMS_FILE.open("r", encoding="utf-8") as f:
        for name, cfg in json.load(f)["presets"].items():
            merged[name] = cfg
    # 2. definition 文件覆盖 (新源优先)
    if DEFINITIONS_DIR.is_dir():
        for def_path in sorted(DEFINITIONS_DIR.glob("*.json")):
            name = def_path.stem
            with def_path.open("r", encoding="utf-8") as f:
                merged[name] = json.load(f)
    rows = []
    for name, cfg in merged.items():
        rows.append({
            "name": name,
            "display_name": cfg.get("display_name", name),
            "category": cfg.get("category", "other"),
            "description": cfg.get("description", ""),
            "order": cfg.get("order", 999),
        })
    rows.sort(key=lambda r: r["order"])
    return rows


def save_definition(preset_name: str, cfg: dict) -> Path:
    """把 preset 配置写到 DEFINITIONS_DIR / f"{preset_name}.json".

    引导向导 (wizard) 用: 用户在向导里定义完输入/输出/示例后, 调这个落盘,
    新工作流立即可在运行页使用 (list_workflows 会扫描 definitions/ 目录).
    """
    import json
    DEFINITIONS_DIR.mkdir(parents=True, exist_ok=True)
    out = DEFINITIONS_DIR / f"{preset_name}.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return out


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