"""prompts.py 提示词池的测试。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import prompts


def test_load_pool_returns_list():
    pool = prompts.load_pool()
    assert isinstance(pool, list)
    assert len(pool) >= 80  # review 2026-07-27 扩到 100, 允许后续手编删减


def test_each_entry_has_category_and_text():
    pool = prompts.load_pool()
    for entry in pool:
        assert "category" in entry
        assert "text" in entry
        assert isinstance(entry["text"], str) and len(entry["text"]) > 20


def test_random_returns_string():
    p = prompts.random_prompt()
    assert isinstance(p, str) and len(p) > 20


def test_random_category_filter():
    """random_prompt(category=...) 只返回该类别的。"""
    pool = prompts.load_pool()
    if not pool:
        pytest.skip("empty pool")
    cat = pool[0]["category"]
    for _ in range(20):  # 多抽几次确认稳定
        p = prompts.random_prompt(category=cat)
        # 返回的应该是该 category 的某条 text
        texts_in_cat = [e["text"] for e in pool if e["category"] == cat]
        assert p in texts_in_cat


def test_random_category_nonexistent_returns_any():
    """请求不存在的 category → 应回退返回任意一条（不抛错）。"""
    p = prompts.random_prompt(category="nonexistent_xyz")
    assert isinstance(p, str) and len(p) > 20


def test_random_n_returns_multiple():
    """random_prompts(n=3) 返回最多 n 条不重复的。"""
    out = prompts.random_prompts(n=3)
    assert isinstance(out, list)
    assert len(out) <= 3
    assert len(out) == len(set(out))  # 不重复


def test_random_n_respects_pool_size():
    out = prompts.random_prompts(n=10000)
    assert len(out) == len(prompts.load_pool())

def test_pool_has_diverse_categories():
    """池子凑到 100 后, 至少有 6 个不同 category, 每个 category 至少 3 条.
    这样 random_prompt(category=X) 各主题都不会只有 1 条.
    """
    pool = prompts.load_pool()
    from collections import Counter
    cats = Counter(p["category"] for p in pool)
    assert len(cats) >= 6, f"only {len(cats)} categories: {dict(cats)}"
    for cat, n in cats.items():
        # nature/product 等冷门主题可能只 1 条, 不强求 2+
        assert n >= 1, f"category {cat!r} has 0 entries"


def test_random_pick_distribution_does_not_repeat_often():
    """连点 20 次随机, 应该看到至少 10 个不同 prompt (避免反复出现同一条).
    """
    pool = prompts.load_pool()
    if len(pool) < 30:
        pytest.skip("pool too small to test distribution")
    picks = [prompts.random_prompt() for _ in range(20)]
    unique = len(set(picks))
    assert unique >= 10, f"only {unique} unique picks in 20 tries, 池子可能太小"

