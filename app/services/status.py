"""状态字符串解析 — wait_for_completion yield 的状态文本分类/解析.

公开符号:
  - _extract_status_kind(msg)    状态类别 (running / error / done / ...)
  - _extract_step_progress(msg)  "KSampler 12/20" 的步数
  - _phase_from_status(msg)      阶段标签 (生成 / LivePortrait / 上采样 / ...)
  - _format_elapsed(secs)        "MM:SS" / "H:MM:SS"
  - _failure_hint(msg)           失败时给用户的可操作建议
"""
from __future__ import annotations

import re

# 匹配 wait_for_completion yield 的 running 消息里的 "value/max" step 进度
# (P0 之后格式: "⏳ MM:SS  running…  KSampler 12/20")。
# 注意: 时间戳是 MM:SS (冒号), 不会误匹配这个斜杠模式。
_STEP_PROGRESS_RE = re.compile(r"(\d+)/(\d+)(?!\d)")

# review 2026-07-21 首递首区域重构:
# 把 _yield_run_stream yield 的 status_msg 拆成 (action, phase_text, detail),
# _run_and_format 用它累积 task_list 喂给 _render_status_html
# (不再叠 60% 胶囊, 改成 task 清单, 进度由 SSE event 的 progress 字段单独管)。
#
# 规则:
#   ⏳ MM:SS  ...    -> live_update (wait_for_completion 长轮询, 只更新当前 task detail)
#   ⏳ <其它>         -> new_task    (phase_text 是阶段名)
#   ✅                -> task_done   (当前 task 标 done, run 也成功结束)
#   ❌                -> task_failed (当前 task 标 failed)
#   ⏰                -> task_timeout
_LIVE_RE = re.compile(rf"^{chr(0x23F3)}\s+\d{{2}}:\d{{2}}\s")


def _extract_status_kind(status_msg):
    if status_msg.startswith("✅"):
        return "success", None
    if status_msg.startswith("❌"):
        return "failure", status_msg[1:].strip()
    if status_msg.startswith("⏰"):
        return "timeout", status_msg[1:].strip()
    return None, None


def _extract_step_progress(status_msg: str) -> tuple[int, int] | None:
    """从 status_msg 抽 step 进度 (value, max), 无则 None。

    用于 P2: 把 wait_for_completion yield 的 "12/20" 抽出来喂给进度展示,
    让顶部固定进度条跟状态条的真实 step 一致 (不再 _wait_p += 0.02 匀速假进度)。

    取 msg 里最后一个 value/max (max>0); 时间戳 MM:SS 用冒号不会误匹配。
    max=0 视为异常 (除零风险) -> None。
    """
    matches = _STEP_PROGRESS_RE.findall(status_msg)
    for value_str, max_str in reversed(matches):
        try:
            v, mx = int(value_str), int(max_str)
        except ValueError:
            continue
        if mx > 0:
            return (v, mx)
    return None


def _phase_from_status(status_msg):
    if not status_msg:
        return ("idle", "", "")
    if status_msg.startswith(chr(0x2705)):
        return ("task_done", "", "")
    if status_msg.startswith(chr(0x274C)):
        return ("task_failed", "", "")
    if status_msg.startswith(chr(0x23F0)):
        return ("task_timeout", "", "")
    if status_msg.startswith(chr(0x23F3)):
        if _LIVE_RE.match(status_msg):
            detail = status_msg[len(chr(0x23F3)):].strip()
            if len(detail) > 50:
                detail = detail[:50] + chr(0x2026)
            return ("live_update", "", detail)
        text = status_msg[len(chr(0x23F3)):].strip()
        if len(text) > 50:
            text = text[:50] + chr(0x2026)
        return ("new_task", text, "")
    return ("idle", "", "")


def _format_elapsed(seconds):
    """把秒数格式化成 mm:ss, 例如 75 -> '01:15'。review P2 让用户感知运行已耗时。"""
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def _failure_hint(msg):
    """Phase 5: 失败/超时时给出具体下一步建议, 而不是只把错误翻给用户。

    按 AGENTS.md 的 Failure-investigation priority (用户输入 → ComfyUI 进程 → 资源 → 工作流),
    根据错误关键词推断最可能的下一步。返回 HTML 行 (空串 = 无匹配建议)。
    """
    if not msg:
        return ''
    low = msg.lower()
    # 关键词 → 建议. 顺序按"最常见 → 最不可能"排列。
    if 'upload' in low or '上传' in msg or 'input dir' in low or 'cannot move' in low:
        return '下一步: 检查文件路径是否含特殊字符 / ComfyUI 的 input 目录是否可写。'
    if 'queue' in low or '入队' in msg or 'connection' in low or 'connect' in low or 'refused' in low:
        return '下一步: 确认 ComfyUI 已启动 (设置 tab 顶部状态灯),端口未被占用。'
    if 'timeout' in low or '超时' in msg or 'timed out' in low:
        return '下一步: 通常是显存/磁盘不足或模型加载慢, 可缩小尺经 / 段数后重试。'
    if 'patch' in low or 'workflow' in low or 'node' in low or 'validator' in low:
        return '下一步: workflow JSON 与 params.json 不一致, 检查最近是否手动改过 preset 配置。'
    if 'cuda' in low or 'out of memory' in low or 'vram' in low or 'memory' in low:
        return '下一步: 显存不足, 缩小输出尺经 / 段数, 或关闭其他占用 GPU 的程序。'
    if 'file' in low and ('too large' in low or 'size' in low or 'big' in low):
        return '下一步: 文件过大, 参考图 ≤5MB / 驱动视频 ≤200MB, 压缩后重试。'
    return ''
