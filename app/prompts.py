"""提示词池 — 文生图的随机提示词来源。

数据存在 app/presets/prompts.json。用户可手动编辑该文件扩充池子。
构造 (review 2026-07-27, 凑到 100 条):
  - 22 条手写 portrait/food/landscape 等多样示例 (保留作者原判)
  - 44 条来自 FollowThisImage/starred 库 (作者标星的真实生成, 质量高)
  - 34 条从 FollowThisImage/history (5553 条) 按 photorealistic + 长度 200-900 筛选, round-robin 按 category 抽样保证多样
category 字段让 random_prompt(category=...) 仍能按主题过滤 (portrait / landscape / food / vehicle / animal / interior / cityscape / product 等).
"""
from __future__ import annotations

import json
import random

from . import config


def _pool_path():
    return config.PRESETS_DIR / "prompts.json"


def load_pool() -> list[dict]:
    """加载提示词池。每项 {"category": str, "text": str}。

    文件不存在或损坏时返回 []，不抛错（文生图仍可手填）。
    """
    p = _pool_path()
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    # 兼容两种格式：直接 list，或 {"prompts": [...]}
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("prompts", [])
    else:
        items = []
    # 归一化：只要 category + text
    return [{"category": e.get("category", "other"), "text": e["text"]}
            for e in items if isinstance(e, dict) and e.get("text")]


def random_prompt(category: str | None = None) -> str:
    """随机返回一条提示词文本。

    category 指定时只从该类别抽；该类别不存在则回退到全池。
    池为空时返回空串（调用方应允许手填）。
    """
    pool = load_pool()
    if not pool:
        return ""
    if category:
        filtered = [e["text"] for e in pool if e["category"] == category]
        if filtered:
            return random.choice(filtered)
    return random.choice([e["text"] for e in pool])


def random_prompts(n: int = 1, category: str | None = None) -> list[str]:
    """随机返回最多 n 条不重复的提示词。"""
    pool = load_pool()
    if not pool:
        return []
    if category:
        texts = [e["text"] for e in pool if e["category"] == category]
    else:
        texts = [e["text"] for e in pool]
    if not texts:
        return []
    k = min(n, len(set(texts)))
    return random.sample(list(dict.fromkeys(texts)), k)
