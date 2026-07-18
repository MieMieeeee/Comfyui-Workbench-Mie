"""排版精致化 组4: emoji baseline + textarea 行高测试。

审计发现:
- emoji (Windows Segoe UI Emoji) baseline 偏高, 无 vertical-align 规则 →
  🚀/📥/🔄/🎬 跟文字基线不齐, "看不出哪里不对但就是别扭"。
- textarea 无 line-height 声明, 继承 Gradio 默认 → CJK 提示词显挤。

收敛方向:
- tokens.css 加 emoji vertical-align 规则 (修 baseline 偏高)。
- textarea rule 加 line-height: var(--leading-normal)。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

TOKENS_CSS = REPO_ROOT / "app" / "static" / "tokens.css"


def test_emoji_vertical_align_rule_exists():
    """tokens.css 有针对 emoji 的 vertical-align 规则。
    审计: Windows Segoe UI Emoji baseline 偏高, 所有 emoji 按钮文字 (🚀/📥/🔄)
    看着跟文字不齐。vertical-align: -0.1em ~ -0.2em 把 emoji 往下拉齐 baseline。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    # 找 vertical-align 规则, 配合 emoji 相关选择器
    # 可接受的形式: emoji 元素, 或含 emoji 的容器 (button/label/heading)
    has_va = "vertical-align" in text
    assert has_va, "tokens.css 完全没有 vertical-align 规则"
    # 找一条 vertical-align 是负值 (-0.1em / -0.15em / -0.2em 这种) 的规则
    # (负值 = 把元素往下拉, 修 emoji 偏高)
    neg_va = re.search(r"vertical-align:\s*-\d", text)
    assert neg_va, \
        "tokens.css 没有负值 vertical-align (修 emoji baseline 偏高需要 -0.1em 量级)"


def test_textarea_has_explicit_line_height():
    """textarea CSS 有显式 line-height 声明 (走 --leading-* token)。
    审计: 提示词输入框 (gr.Textbox max_lines=6) 是最重要的多行表面, 但没 line-height,
    继承 Gradio 默认 (~1.5 但不管), CJK 提示词显挤。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    # 找 textarea 规则块
    m = re.search(r"(?:\.gradio-container\s+)?textarea\s*\{([^}]*)\}", text, re.S)
    if m is None:
        # 也可能是 input[type] 组合规则里含 textarea
        m = re.search(r"textarea[^{]*\{([^}]*)\}", text, re.S)
    assert m, "tokens.css 没有 textarea CSS 规则"
    body = m.group(1)
    assert "line-height" in body, \
        f"textarea 规则没有 line-height 声明 (body={body}); 应加 var(--leading-normal)"
    assert "--leading-" in body, \
        f"textarea line-height 没走 --leading-* token (body={body})"


def test_leading_tokens_consumed_in_main_surfaces():
    """回归锁: --leading-* token 现在被 textarea 消费了 (之前只在 annotation/blockquote)。
    保证 line-height 改动走 token, 不硬编码像素值。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    # textarea 之外, 确认 leading token 仍在被消费 (annotation / blockquote / textarea)
    leading_uses = len(re.findall(r"var\(--leading-", text))
    assert leading_uses >= 3, \
        f"--leading-* token 消费点 < 3 (={leading_uses}); textarea 应新增一个消费点"
