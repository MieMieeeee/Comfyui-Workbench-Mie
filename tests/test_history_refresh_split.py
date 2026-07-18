"""历史 tab 拆分刷新 handler —— 单元测试 (TDD)。

锁定的契约:
  1. _refresh_history_dataframe 只更新 Dataframe (rows) + cache, 不动详情面板。
  2. _refresh_history_details 只读 cache 渲染详情面板 + count_label, 不重新读盘。
  3. _refresh_history_filtered 仍存在(向后兼容 + tab.select / refresh_btn 复用),
     内部委托给上面两个 helper。
  4. _HISTORY_RUNS_CACHE 在 _refresh_history_dataframe 调用后被填,
     _refresh_history_details 从 cache 读 (不会重新调 list_runs)。

为什么拆:
  - 现状 _refresh_history_filtered 同时返回 6 个 output (df + 5 个详情组件),
    在 .change (preset_filter / status_filter) 上重跑这个 handler 会:
    a) 重新读盘 (每次筛选切换都 list_runs 一次)
    b) 把详情面板也重渲 (跟筛选无关, 用户切 preset 时详情不需要变)
    c) 把 _make_detail_from_run 也跑一次 (可能很贵)
  - 拆分后 .change 只刷 Dataframe, 详情保持选中行不变。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app, history


def _fake_run(pid, preset="zimage", status="success", prompt="hello"):
    return {
        "prompt_id": pid,
        "created_at": "2026-07-17T10:00:00",
        "preset": preset,
        "status": status,
        "duration_sec": 42,
        "prompt_text": prompt,
    }


# --- _refresh_history_dataframe ---

def test_refresh_history_dataframe_exists():
    """_refresh_history_dataframe 存在 (拆分出的 Dataframe-only handler)。"""
    assert callable(getattr(scail2_app, "_refresh_history_dataframe", None)), \
        "缺 _refresh_history_dataframe — _refresh_history_filtered 应被拆成 df-only + details-only"


def test_refresh_history_dataframe_returns_only_rows():
    """_refresh_history_dataframe 只返回 rows (list[list[str]]), 不返回详情组件。
    拆分的目的是: .change 事件只刷 Dataframe, 详情面板保持不变。"""
    scail2_app._HISTORY_RUNS_CACHE.clear()
    with patch.object(scail2_app.history, "list_runs",
                      return_value=[_fake_run("p0"), _fake_run("p1")]):
        result = scail2_app._refresh_history_dataframe("全部", "全部")
    # 返回值必须是 list[list[str]], 长度等于 runs 数
    assert isinstance(result, list), f"应返回 list, 实际 {type(result)}"
    assert len(result) == 2, f"应返回 2 行, 实际 {len(result)}"
    for row in result:
        assert isinstance(row, list), f"每行应是 list, 实际 {type(row)}"
        assert len(row) == 6, f"每行 6 列, 实际 {len(row)}"


def test_refresh_history_dataframe_updates_cache():
    """调用后 _HISTORY_RUNS_CACHE[(preset, status)] 被填。
    _refresh_history_details 后面从 cache 读, 不能重新调 list_runs。"""
    scail2_app._HISTORY_RUNS_CACHE.clear()
    fake_runs = [_fake_run("p0"), _fake_run("p1")]
    with patch.object(scail2_app.history, "list_runs", return_value=fake_runs):
        scail2_app._refresh_history_dataframe("zimage", "success")
    cache = scail2_app._HISTORY_RUNS_CACHE.get(("zimage", "success"))
    assert cache is not None, "_refresh_history_dataframe 没填 cache"
    assert len(cache) == 2
    assert cache[0]["prompt_id"] == "p0"


def test_refresh_history_dataframe_filters_none_become_all():
    """_refresh_history_dataframe("全部", "全部") 跟传 None 等价。
    list_runs 收到 None/All 都不过滤, cache 用 ("全部", "全部") 作 key (跟 select handler 收到的 raw 一致)。"""
    scail2_app._HISTORY_RUNS_CACHE.clear()
    fake_runs = [_fake_run("p0")]
    with patch.object(scail2_app.history, "list_runs", return_value=fake_runs) as m:
        scail2_app._refresh_history_dataframe("全部", "全部")
    # cache key 是 ("全部", "全部") 而不是 (None, None)
    assert ("全部", "全部") in scail2_app._HISTORY_RUNS_CACHE
    # list_runs 收到 None/None (“全部”被映射成 None 过滤传给 history API)
    m.assert_called_once()
    kwargs = m.call_args.kwargs
    assert kwargs.get("preset") is None, f"list_runs preset 应是 None, 实际 {kwargs}"
    assert kwargs.get("status") is None, f"list_runs status 应是 None, 实际 {kwargs}"


# --- _refresh_history_details ---

def test_refresh_history_details_exists():
    """_refresh_history_details 存在。"""
    assert callable(getattr(scail2_app, "_refresh_history_details", None)), \
        "缺 _refresh_history_details — 详情面板应有独立的 handler"


def test_refresh_history_details_returns_5_outputs():
    """_refresh_history_details 返回 (summary_html, media_html, json_str, prompt_md, count_label)。
    5 个, 跟 _build_history_tab 里 detail_outputs + count_label 匹配。"""
    scail2_app._HISTORY_RUNS_CACHE.clear()
    scail2_app._HISTORY_RUNS_CACHE[("全部", "全部")] = [_fake_run("p0")]
    result = scail2_app._refresh_history_details("全部", "全部")
    assert isinstance(result, tuple)
    assert len(result) == 5, f"应返回 5 元组, 实际 {len(result)}"


def test_refresh_history_details_reads_from_cache():
    """_refresh_history_details 不调 list_runs, 只从 cache 读。
    关键: 如果误调 list_runs, 详情会跟筛选出来的最新 runs 一致 (而不是 cache 里的),
    跟 _refresh_history_dataframe 写的 cache 出现竞态。"""
    scail2_app._HISTORY_RUNS_CACHE.clear()
    scail2_app._HISTORY_RUNS_CACHE[("全部", "全部")] = [_fake_run("p0", prompt="cached")]
    with patch.object(scail2_app.history, "list_runs") as m:
        scail2_app._refresh_history_details("全部", "全部")
    m.assert_not_called(), "_refresh_history_details 不应调 list_runs (应从 cache 读)"


def test_refresh_history_details_count_label_reflects_cache():
    """count_label 反映 cache 里 runs 数量, 不是磁盘。"""
    scail2_app._HISTORY_RUNS_CACHE.clear()
    # 3 条放 cache, 但 list_runs 假装返回 100 条 (不应被读)
    scail2_app._HISTORY_RUNS_CACHE[("全部", "全部")] = [
        _fake_run("p0"), _fake_run("p1"), _fake_run("p2"),
    ]
    with patch.object(scail2_app.history, "list_runs",
                      return_value=[_fake_run(f"x{i}") for i in range(100)]):
        _, _, _, _, count_label = scail2_app._refresh_history_details("全部", "全部")
    assert "3" in count_label, f"count_label 应是 cache 里 3 条, 实际: {count_label}"
    assert "100" not in count_label, f"count_label 误读了 list_runs (100 条): {count_label}"


def test_refresh_history_details_empty_cache_returns_empty_placeholder():
    """cache 为空 → 详情返回空占位 (不抛)。
    边界: 用户开 tab 但 cache 没填 (e.g. demo.load 没跑 / tab.select 还没触发)。
    review 2026-07-18: json_str empty placeholder is a dict, NOT a str --
    gr.JSON.postprocess("") raises "Invalid JSON string: Input is a zero-length, empty document"."""
    scail2_app._HISTORY_RUNS_CACHE.clear()
    summary, media, json_str, prompt_md, count_label = \
        scail2_app._refresh_history_details("全部", "全部")
    # 5 个值都有 placeholder; json_str 是 dict (空 cache / no rows)
    assert isinstance(summary, str)
    assert isinstance(media, str)
    assert isinstance(json_str, dict), f"empty cache json_str should be dict, got {type(json_str).__name__}: {json_str!r}"
    assert isinstance(prompt_md, str)
    assert "0" in count_label


# --- _refresh_history_filtered 兼容性 ---

def test_refresh_history_filtered_still_exists_and_returns_6_tuple():
    """_refresh_history_filtered 仍存在, 返回 6 元组 (向后兼容, 给 tab.select / refresh_btn 用)。
    内部委托给两个新 helper。"""
    scail2_app._HISTORY_RUNS_CACHE.clear()
    fake_runs = [_fake_run("p0"), _fake_run("p1")]
    with patch.object(scail2_app.history, "list_runs", return_value=fake_runs):
        result = scail2_app._refresh_history_filtered("全部", "全部")
    assert isinstance(result, tuple)
    assert len(result) == 6, f"应返回 6 元组 (向后兼容), 实际 {len(result)}"
    rows = result[0]
    assert isinstance(rows, list) and len(rows) == 2


def test_refresh_history_filtered_populates_cache():
    """_refresh_history_filtered 调一次, cache 填上 (这样后续 .change → details 能从 cache 读)。"""
    scail2_app._HISTORY_RUNS_CACHE.clear()
    with patch.object(scail2_app.history, "list_runs",
                      return_value=[_fake_run("p0")]):
        scail2_app._refresh_history_filtered("zimage", "success")
    assert ("zimage", "success") in scail2_app._HISTORY_RUNS_CACHE
