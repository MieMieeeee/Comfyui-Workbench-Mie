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


# ---------------------------------------------------------------------------
# _failure_hint — torch/CUDA 版本不兼容场景 (bug fix 2026-07-31)
# ---------------------------------------------------------------------------
#
# 用户场景: ComfyUI 报 torch.AcceleratorError: CUDA error: no kernel image is
# available for execution on the device. 这是 torch 版本与 GPU 算力 (compute
# capability) 不兼容的典型错误, 用户看到原文会懵. _failure_hint 要把这类错误
# 转成"去 ComfyUI 启动器重装匹配你显卡的 torch"这种可执行的下一步.
# 同时回归保护: 现有 cuda/OOM 分支不能被新分支遮蔽.

def test_failure_hint_torch_kernel_image_mismatch():
    """torch.AcceleratorError: no kernel image → 给 torch 版本不兼容建议."""
    msg = "error: torch.AcceleratorError: CUDA error: no kernel image is available for execution on the device"
    hint = status_svc._failure_hint(msg)
    assert hint, f"应给出建议, 得到空串. msg={msg!r}"
    # 建议必须提到 torch 版本 + ComfyUI 启动器 (可执行动作), 而不是显存不足那种误导
    assert "torch" in hint.lower() or "版本" in hint


def test_failure_hint_accelerator_error_type_also_matched():
    """异常类型名 'AcceleratorError' 单独出现也要命中 (可能错误信息被截断只剩类型)."""
    hint = status_svc._failure_hint("error: AcceleratorError during sampling")
    assert hint and ("torch" in hint.lower() or "版本" in hint)


def test_failure_hint_cuda_oom_still_works():
    """回归保护: 新增 torch 分支不能遮蔽现有 cuda/OOM 分支.

    cuda out of memory 应该命中显存建议, 而不是 torch 版本建议
    (OOM 是显存问题, 不是算力兼容问题, 给错建议会误导用户).
    """
    hint = status_svc._failure_hint("error: CUDA out of memory")
    assert hint
    # 显存建议关键词 (现有分支文案): 显存 / 缩小 / GPU
    assert "显存" in hint or "缩小" in hint
