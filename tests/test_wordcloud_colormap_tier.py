"""WordCloud colormap spec should be in basic tier, not advanced.

用户反馈: "风格不应该是高级参数"。
Colormap (配色方案) 是 wordcloud 的核心可视化选项之一,用户在选择
"图生词云"预设时第一眼就该看到。隐藏在"高级参数"折叠里违背了
review 2026-07-17 §"高级参数"语义 (= 一般不用改) 的初衷。
"""
from __future__ import annotations

import sys
from pathlib import Path
import json

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import config


PARAMS_PATH = REPO_ROOT / "app" / "presets" / "params.json"


def test_wordcloud_colormap_tier_is_basic():
    """wordcloud 预设的 colormap 字段必须 tier=basic (用户核心可视化选择)。"""
    cfg = config.preset_config("wordcloud")
    colormap_spec = next(
        s for s in cfg["user_facing_inputs"]
        if s.get("field") == "colormap"
    )
    assert colormap_spec.get("tier") == "basic", (
        f"wordcloud colormap should be tier=basic (用户可视化核心选项), "
        f"got tier={colormap_spec.get('tier')!r}"
    )


def test_wordcloud_params_json_colormap_tier_is_basic():
    """params.json 物理文件里 wordcloud colormap 也是 basic (防 config_cache 漂移)。"""
    raw = json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
    wc = raw["presets"]["wordcloud"]
    colormap_spec = next(
        s for s in wc["user_facing_inputs"]
        if s.get("field") == "colormap"
    )
    assert colormap_spec.get("tier") == "basic", (
        f"params.json wordcloud colormap.tier should be 'basic', "
        f"got {colormap_spec.get('tier')!r}"
    )
