"""RunEvent 数据类 + 流式 runner — 桥接 scail2_app 的 generator 到 SSE.

步骤 4: 把 scail2_app.run_workflow / run_image_workflow 的 (status_msg, media)
yield 流包成 RunEvent, 供 Flask /api/run/<preset> 转 SSE.

设计决策 (务实方案):
  不重写 run_workflow / run_image_workflow 的 280+211 行编排逻辑, 直接复用.
  scail2_app.run_workflow 里的 gr.Progress() 是个 no-op (只记录), gr.Error(msg)
  抛异常 —— 我们在 SSE handler 里捕获这些异常转成 error event.

  这意味着 Flask 版仍依赖 scail2_app 能 import gradio. 步骤 7 (下线 Gradio) 时
  才真正把 run_workflow 的编排逻辑剥离 gradio 依赖.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict, field
from typing import Any, Iterator, Literal

from app import config
from app import scail2_app  # 复用 run_workflow / run_image_workflow / _media_to_html / _output_kind
from app.services import status as status_svc
from app.services import persistence

_log = logging.getLogger("scail2_app.runner")


@dataclass
class RunEvent:
    """SSE 事件数据类. 每个字段对应前端一个 UI 更新点.

    type:
      - 'log'     常规状态更新 (前端追加到日志, 更新状态条)
      - 'media'   有 media 产出 (前端把 media_html 填进结果区)
      - 'error'   错误/超时 (前端显示 error_html 红条)
      - 'done'    generator 结束 (前端解除 running 状态)
    """
    type: Literal["log", "media", "error", "done"]
    log: str | None = None              # 累积日志 (最近 N 条)
    status_msg: str | None = None       # 当前 status 消息 (✅/❌/⏰ 前缀)
    media_url: str | None = None        # 原始 URL
    media_html: str | None = None       # 已渲染的 HTML (scail2_app._media_to_html 产出)
    error_html: str | None = None       # 错误条 HTML (失败/超时)
    state: str | None = None            # idle/running/success/failure/timeout
    elapsed_sec: float | None = None
    progress: tuple[int, int] | None = None  # (current, max) step

    def to_sse(self) -> str:
        """转成 SSE 'data: ...\\n\\n' 行."""
        d = asdict(self)
        # progress tuple 转成 list (JSON 不支持 tuple)
        if d.get("progress") is not None:
            d["progress"] = list(d["progress"])
        return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"


def stream_events(
    preset_name: str,
    form_values: list,
    *,
    on_success: callable = None,
) -> Iterator[RunEvent]:
    """运行 preset, yield RunEvent 流.

    Args:
      preset_name: preset 名
      form_values: 按 user_facing_inputs 顺序的扁平值列表 (跟 scail2_app 期望的
                   component_values 一致). int_random 占 2 位 (checkbox + number).
      on_success: 可选回调, 成功时调用 (preset_name, form_values), 用于 _save_last_run.

    Yields:
      RunEvent 流, 最后必有 'done' 事件.
    """
    preset_cfg = config.preset_config(preset_name)
    output_kind = scail2_app._output_kind(preset_cfg)
    run_fn = scail2_app.run_image_workflow if output_kind == "image" else scail2_app.run_workflow

    log_lines: list[str] = []
    last_media = None
    final_state = "failure"
    start_ts = time.monotonic()

    def _elapsed() -> float:
        return time.monotonic() - start_ts

    try:
        for status_msg, media in run_fn(preset_name, *form_values):
            log_lines.append(status_msg)
            if media:
                last_media = media

            # 推断 state
            kind, err = status_svc._extract_status_kind(status_msg)
            if kind == "success":
                final_state = "success"
                state = "success"
            elif kind == "failure":
                final_state = "failure"
                state = "failure"
            elif kind == "timeout":
                final_state = "timeout"
                state = "timeout"
            else:
                state = "running"

            # 抽 step 进度
            step = status_svc._extract_step_progress(status_msg)

            # 错误条 HTML
            error_html = None
            if kind == "failure":
                error_html = f"<div class='error-banner-inner'><b>运行失败</b><br>{err}</div>"
            elif kind == "timeout":
                error_html = f"<div class='error-banner-inner'><b>运行超时</b><br>{err}</div>"

            # media HTML
            media_html = None
            if media:
                media_html = scail2_app._media_to_html(media, output_kind)

            event_type = "media" if media_html else ("error" if error_html else "log")
            yield RunEvent(
                type=event_type,
                log="\n".join(log_lines[-12:]),
                status_msg=status_msg,
                media_url=str(media) if media else None,
                media_html=media_html,
                error_html=error_html,
                state=state,
                elapsed_sec=_elapsed(),
                progress=step,
            )

            # 成功时触发 _save_last_run 回调
            if kind == "success" and on_success is not None:
                try:
                    on_success(preset_name, form_values)
                except Exception as e:
                    _log.warning(f"on_success callback failed: {e}")

            # 终态后退出
            if kind in ("success", "failure", "timeout"):
                break

    except Exception as exc:
        _log.exception("stream_events exception: %s", exc)
        # scail2_app.run_workflow 里 gr.Error(msg) 会抛 gradio.Error, msg 在 str(exc)
        err_msg = str(exc) or repr(exc)
        log_lines.append("❌ " + err_msg)
        yield RunEvent(
            type="error",
            log="\n".join(log_lines[-12:]),
            status_msg="❌ " + err_msg,
            error_html=f"<div class='error-banner-inner'><b>运行异常</b><br>{err_msg}</div>",
            state="failure",
            elapsed_sec=_elapsed(),
        )

    # done 事件 (保留最后 media)
    final_media_html = None
    if last_media:
        final_media_html = scail2_app._media_to_html(last_media, output_kind)
    yield RunEvent(
        type="done",
        log="\n".join(log_lines[-12:]),
        media_html=final_media_html,
        media_url=str(last_media) if last_media else None,
        state=final_state,
        elapsed_sec=_elapsed(),
    )
