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
    assert len(pool) >= 15  # 至少十几条


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
