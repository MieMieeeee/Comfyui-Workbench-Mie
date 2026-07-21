"""P3-9 regression lock: status bar must have punctuation between label and msg.

review P3-9 (2026 July 17): currently `_render_status_html('idle', msg)` concatenates
state label + msg without separator. Result: `⏸等待运行点击下方按钮开始`
("⏸ waiting to run click button below to start") -- no internal punctuation, reads
like one mashed-together sentence.

Contract: rendered text from `_render_status_html(state, msg)` must have a visible
separator (we accept "." / "·" / "," / "。" / "—" etc.) between
the state label and msg text. Most natural fix: insert " · " in the helper.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import scail2_app


def _strip_tags(html: str) -> str:
    """Drop HTML tags, keep visible text. Collapse whitespace."""
    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\s+", " ", text).strip()


def test_status_html_idle_has_separator_between_label_and_msg():
    """idle state must not produce 'waiting to run click below button to start' mashed text."""
    html = scail2_app._render_status_html("idle", "点击下方按钮开始, 或先点上方「加载示例素材」")
    text = _strip_tags(html)
    label = "等待运行"
    msg = "点击下方按钮开始"
    assert label in text and msg in text, f"label/msg missing: {text!r}"
    # find position of label and msg
    li = text.index(label)
    mi = text.index(msg)
    between = text[li + len(label):mi]
    assert between.strip(), (
        f"no separator between label and msg; rendered text = {text!r}. "
        f"review P3-9: insert ' · ' (or other punctuation) between them."
    )


def test_status_html_running_has_separator():
    """running state must follow the same contract."""
    html = scail2_app._render_status_html("running", "提示词已提交, 请耐心等待")
    text = _strip_tags(html)
    label = "正在运行"
    msg = "提示词已提交"
    assert label in text and msg in text, f"label/msg missing: {text!r}"
    li = text.index(label)
    mi = text.index(msg)
    between = text[li + len(label):mi]
    assert between.strip(), f"no separator: {text!r}"
