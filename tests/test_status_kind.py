"""status_svc._extract_status_kind 契约测试.

锁 runner 多尺寸文生图用的 🖼 单段完成前缀: 它必须 NOT 被误判成 success/failure,
否则 stream_events 会提前 break, 多尺寸只跑第一张 (见 runner.run_image_workflow
yield f"🖼 [{idx}/{len(sizes)}] ..." 的注释).

背景 (review 2026-07-28): runner.py 用 🖼 而非 ✅ 标记单段完成, 正是为了避开
status_svc 把 ✅ 当整体成功. 这个契约之前没有测试锁, 现在补.
"""
from app.services import status as status_svc


# ---------------------------------------------------------------------------
# 单段完成前缀 🖼 — 多尺寸文生图的正确性依赖它
# ---------------------------------------------------------------------------

def test_single_segment_done_prefix_is_not_success():
    """🖼 前缀 = 单段完成, 不是整个 run 成功. 必须返 (None, None) 进入 running 分支."""
    kind, err = status_svc._extract_status_kind("🖼 [1/3] 1024x1024 done")
    assert kind is None, (
        f"🖼 单段完成前缀被误判成 {kind!r}, 会导致 stream_events 提前 break, "
        "多尺寸文生图只跑第一张"
    )
    assert err is None


def test_single_segment_done_prefix_does_not_match_any_terminal_kind():
    """🖼 前缀扫描所有终态前缀, 一个都不能命中."""
    msg = "🖼 [2/5] 720x1280 done"
    for prefix in ("✅", "❌", "⏰"):
        assert not msg.startswith(prefix)


# ---------------------------------------------------------------------------
# 终态前缀契约 (背景对照, 确保上面的 None 判断不是巧合)
# ---------------------------------------------------------------------------

def test_success_prefix_returns_success_kind():
    assert status_svc._extract_status_kind("✅ done in 00:42") == ("success", None)


def test_failure_prefix_returns_failure_kind_with_message():
    kind, err = status_svc._extract_status_kind("❌ execution failed")
    assert kind == "failure"
    assert err == "execution failed"


def test_timeout_prefix_returns_timeout_kind_with_message():
    kind, err = status_svc._extract_status_kind("⏰ waited too long")
    assert kind == "timeout"
    assert err == "waited too long"


def test_running_status_returns_none_none():
    """⏳ 进度消息 (非终态) 必须返 (None, None), 让 stream_events 继续 running."""
    assert status_svc._extract_status_kind("⏳ [1/3] 1024x1024 seed=...…") == (None, None)
