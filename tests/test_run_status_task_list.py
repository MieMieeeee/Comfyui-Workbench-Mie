"""run-status-bar task list 渲染 + CSS (review 2026-07-21 进度区域重构)。

覆盖:
- tokens.css 有 .run-status-tasks 块, 跟 .run-status-task-* 子状态对应
- _render_status_html 接 task_list 时渲染 <ul class="run-status-tasks">, 每行
  一个 <li class="run-status-task run-status-task-{status}">, 状态决定 icon。
- 不传 task_list -> 退回到旧版单条 msg (向后兼容锁)
- _render_status_html 不再生成 .run-status-progress 胶囊 (避免和 gr.Progress
  在作品预览那条进度条上重复显示百分比)
- 失败/超时 hint row 仍按 Phase 5 渲染
- _phase_from_status 助手正确分类 new_task / live_update / task_done /
  task_failed / task_timeout

为什么: 进度区域原本叠了 60% 胶囊 + gr.Progress 进度条, 信息冗余;
改用 task 清单只列当前跑哪一步/前面几步完成没, 进度条归作品预览独占。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app

TOKENS_CSS = REPO_ROOT / "app" / "static" / "tokens.css"


def _extract_css_blocks(text: str, selector: str) -> list[str]:
    """从 CSS 文本里抠出所有以 selector 开头的复合选择器块 (.run-status-task-done .foo { ... }).
    返回每个块的 body (大括号内的内容)。
    """
    pat = re.compile(re.escape(selector) + r"[^{}]*\{([^}]*)\}", re.S)
    return [m.group(1) for m in pat.finditer(text)]


def _extract_css_block(text: str, selector: str) -> str | None:
    """返回第一个匹配块 (向后兼容)."""
    blocks = _extract_css_blocks(text, selector)
    return blocks[0] if blocks else None


# --- _phase_from_status 分类 ---

def test_phase_from_status_new_task_for_discrete_phases():
    """⏳ 开头的离散阶段 (无 MM:SS 时间戳) -> new_task + phase_text。"""
    cases = [
        (chr(0x23F3) + " 准备中" + chr(0x2026), "准备中" + chr(0x2026)),
        (chr(0x23F3) + " 上传参考图" + chr(0x2026), "上传参考图" + chr(0x2026)),
        (chr(0x23F3) + " [1/4] 1024x1024 seed=12345" + chr(0x2026), "[1/4] 1024x1024 seed=12345" + chr(0x2026)),
    ]
    for msg, expected_text in cases:
        action, text, detail = scail2_app._phase_from_status(msg)
        assert action == "new_task", repr(msg) + " 应该是 new_task, got " + action
        assert text == expected_text, repr(msg) + " phase_text 不对: " + repr(text)
        assert detail == ""

def test_phase_from_status_live_update_for_long_poll():
    """⏳ MM:SS ... 是 wait_for_completion 的长轮询, 当作 live_update,
    整条不进 task_list, 只更新当前 task 的 detail。"""
    cases = [
        (chr(0x23F3) + " 00:05  waiting for abc12345" + chr(0x2026), "00:05  waiting for abc12345" + chr(0x2026)),
        (chr(0x23F3) + " 00:08  running" + chr(0x2026) + "  KSampler 12/20", "00:08  running" + chr(0x2026) + "  KSampler 12/20"),
    ]
    for msg, expected_detail in cases:
        action, text, detail = scail2_app._phase_from_status(msg)
        assert action == "live_update", repr(msg) + " 应该是 live_update, got " + action
        assert detail == expected_detail, repr(msg) + " detail 不对: " + repr(detail)

def test_phase_from_status_terminal_events():
    """✅ / ❌ / ⏰ 都是终态: task_done / task_failed / task_timeout。"""
    assert scail2_app._phase_from_status(chr(0x2705) + " 完成")[0] == "task_done"
    assert scail2_app._phase_from_status(chr(0x2705) + " 全部完成, 共 4 张图")[0] == "task_done"
    assert scail2_app._phase_from_status(chr(0x274C) + " upload failed")[0] == "task_failed"
    assert scail2_app._phase_from_status(chr(0x23F0) + " timeout after 30 min")[0] == "task_timeout"
    assert scail2_app._phase_from_status("")[0] == "idle"
    assert scail2_app._phase_from_status(None)[0] == "idle"

def test_phase_from_status_long_text_truncated():
    """phase_text 超过 50 字符截断 + 省略号, 防止 task 行溢出。"""
    long_msg = chr(0x23F3) + " " + ("啊" * 80)
    action, text, _ = scail2_app._phase_from_status(long_msg)
    assert action == "new_task"
    assert len(text) <= 51  # 50 + chr(0x2026)
    assert text.endswith(chr(0x2026))


# --- _render_status_html 渲染: task_list 路径 ---

def test_render_status_html_renders_task_list_ul():
    """task_list -> 渲染 ul.run-status-tasks, 每行一个 li.run-status-task-*."""
    tl = [
        {"text": "准备中" + chr(0x2026), "status": "done", "detail": ""},
        {"text": "上传参考图" + chr(0x2026), "status": "done", "detail": ""},
        {"text": "等待 ComfyUI 执行", "status": "current", "detail": "KSampler 12/20"},
    ]
    html = scail2_app._render_status_html("running", "", "01:23", tl)
    assert chr(0x3C) + "ul class=" + chr(0x22) + "run-status-tasks" + chr(0x22) + chr(0x3E) in html
    assert html.count("li class=" + chr(0x22) + "run-status-task run-status-task-done" + chr(0x22)) == 2
    assert "li class=" + chr(0x22) + "run-status-task run-status-task-current" + chr(0x22) in html
    assert "等待 ComfyUI 执行" in html
    assert "KSampler 12/20" in html

def test_render_status_html_task_icons_per_status():
    """task 状态 -> 对应 icon: done=✓, current=◉, pending=○, failed=✗."""
    tl = [
        {"text": "T1", "status": "done"},
        {"text": "T2", "status": "current"},
        {"text": "T3", "status": "pending"},
        {"text": "T4", "status": "failed"},
    ]
    html = scail2_app._render_status_html("running", "", "00:01", tl)
    assert chr(0x2713) in html  # ✓
    assert chr(0x25C9) in html  # ◉
    assert chr(0x25CB) in html  # ○
    assert chr(0x2717) in html  # ✗

def test_render_status_html_no_progress_chip():
    """review 2026-07-21: 进度区域不再渲染 60% 胶囊 (避免和 gr.Progress 重复)."""
    tl = [{"text": "等待执行", "status": "current"}]
    html = scail2_app._render_status_html("running", "", "00:42", tl)
    assert "run-status-progress" not in html, (
        "进度区域不该再有 .run-status-progress 胶囊, 那是 gr.Progress 的活"
    )

def test_render_status_html_no_task_list_falls_back_to_msg():
    """不传 task_list -> 走旧版单条 msg 路径 (idle / 初始化兼容锁)."""
    html = scail2_app._render_status_html("idle", "点击下方按钮开始")
    assert "run-status-tasks" not in html
    assert "点击下方按钮开始" in html
    assert "run-status-msg" in html

def test_render_status_html_task_list_with_empty_detail():
    """task 没 detail 时只渲染 text, 不留空 span."""
    tl = [{"text": "T1", "status": "done"}]
    html = scail2_app._render_status_html("running", "", "00:01", tl)
    assert "T1" in html
    assert "run-status-task-detail" not in html

def test_render_status_html_failure_state_still_renders_hint():
    """Phase 5 hint row 不受 task_list 重构影响, failure/timeout 仍按关键词给建议."""
    html = scail2_app._render_status_html(
        "failure",
        chr(0x274C) + " upload ref: ConnectionError",
        "",
        [{"text": "上传参考图", "status": "failed"}],
    )
    assert "run-status-hint" in html
    assert "input 目录" in html


# --- CSS ---

def test_tokens_css_has_run_status_tasks_block():
    text = TOKENS_CSS.read_text(encoding="utf-8")
    assert _extract_css_block(text, ".run-status-tasks") is not None, \
        "tokens.css 缺 .run-status-tasks 块"

def test_tokens_css_has_run_status_task_substates():
    """.run-status-task-done / -current / -pending / -failed 4 个子状态都应有样式."""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    for sel in [
        ".run-status-task-done",
        ".run-status-task-current",
        ".run-status-task-pending",
        ".run-status-task-failed",
    ]:
        assert _extract_css_block(text, sel) is not None, "tokens.css 缺 " + sel + " 块"

def test_tokens_css_run_status_task_current_uses_theme_accent():
    """.run-status-task-current 必须在某个子块里用 --theme-accent-* 着色
    (icon / detail 子块, 跟 .run-status-running 左边框同色)."""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    blocks = _extract_css_blocks(text, ".run-status-task-current")
    assert blocks, "缺 .run-status-task-current 子块"
    assert any("--theme-accent" in b for b in blocks), \
        ".run-status-task-current 至少有一个子块应该消费 --theme-accent-*"

def test_tokens_css_run_status_task_failed_uses_error_color():
    """.run-status-task-failed 用 --color-error (跟 .run-status-failure 同色)."""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_css_block(text, ".run-status-task-failed")
    assert body is not None
    assert "--color-error" in body

def test_tokens_css_progress_chip_block_removed():
    """.run-status-progress 胶囊样式必须从 tokens.css 拿掉 (review 2026-07-21 重构)."""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    assert _extract_css_block(text, ".run-status-progress") is None, \
        ".run-status-progress 块应当已删除, 进度条归 gr.Progress (作品预览) 独占"

def test_tokens_css_task_detail_is_mono_compact():
    """.run-status-task-detail 跟 .run-status-elapsed 同风格 (mono / 小字号)."""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    body = _extract_css_block(text, ".run-status-task-detail")
    assert body is not None
    assert "mono" in body or "font-mono" in body

