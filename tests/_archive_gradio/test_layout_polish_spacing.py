"""排版精致化 组5: 页脚呼吸 + 按钮 padding 家族统一测试。

审计发现:
- .btn-run-primary 水平 padding --space-6 (24), secondary --space-5 (20) →
  同一栏两个按钮宽度不一致, 不像同一个家族。
- .preset-panels-host gap:0 (Gradio 6 visible=False bug workaround, 锁定不能改) →
  限制说明 <small> 页脚贴着 preset panel 底部, 无呼吸。

收敛方向:
- .btn-run-secondary 水平 padding --space-5 → --space-6 (跟 primary 统一)。
- 页脚 <small> 加 margin-top (在 host 外/不破坏 gap:0 契约)。

锁定边界:
- .preset-panels-host gap 必须 = 0 (test_css_theming.py 锁)。
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


def _extract_css_block(text: str, selector: str) -> str | None:
    pat = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}", re.S)
    m = pat.search(text)
    return m.group(1) if m else None


# --- 按钮家族 padding 统一 ---

def test_run_buttons_share_horizontal_padding_token():
    """.btn-run-primary 和 .btn-run-secondary 水平 padding 用同一个 token。
    审计: primary --space-6 (24px), secondary --space-5 (20px), 同栏两按钮宽度不一致。
    统一后两按钮左右 padding 一样, 视觉上是同一个家族 (primary 靠颜色/字号区分, 不靠宽度)。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    prim = _extract_css_block(text, ".btn-run-primary") or ""
    sec = _extract_css_block(text, ".btn-run-secondary") or ""
    # 抽 padding 的第二个值 (水平), 格式 padding: VERT HORIZ
    def _horiz(block):
        m = re.search(r"padding:\s*\S+\s+(var\(--space-\d\))", block)
        return m.group(1) if m else None
    ph = _horiz(prim)
    sh = _horiz(sec)
    assert ph and sh, f"primary/secondary padding 抽不出水平值 (prim={ph}, sec={sh})"
    assert ph == sh, \
        f"两按钮水平 padding 不一致: primary={ph}, secondary={sh}; 应统一"


def test_run_buttons_min_width_consistent_family():
    """回归锁: 统一 padding 后 min-width 仍合理 (primary >= secondary, 主按钮不窄于次)。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    prim = _extract_css_block(text, ".btn-run-primary") or ""
    sec = _extract_css_block(text, ".btn-run-secondary") or ""
    pmw = re.search(r"min-width:\s*(\d+)px", prim)
    smw = re.search(r"min-width:\s*(\d+)px", sec)
    if pmw and smw:
        assert int(pmw.group(1)) >= int(smw.group(1)), \
            f"primary min-width {pmw.group(1)} < secondary {smw.group(1)}"


# --- 页脚呼吸 ---

def test_footer_limit_notice_has_breathing_room():
    """限制说明 <small> 页脚跟上方 preset panel 之间有间距 (不贴着)。
    审计: .preset-panels-host gap:0 (锁定) 让页脚贴 panel 底部。
    解决: 给页脚加 margin-top (走 elem_classes 或内联, 不动 host gap)。"""
    import inspect
    src = inspect.getsource(scail2_app.build_ui)
    # 找限制说明那段 Markdown, 检查它有 margin-top 或外层有间距类
    assert "限制" in src, "build_ui 找不到限制说明页脚"
    # 页脚 Markdown 调用要带 elem_classes (给 CSS hook 加 margin-top)。
    # 用宽松检查: "限制" 附近 (前后 600 字符内) 出现 elem_classes
    idx = src.find("限制")
    nearby = src[max(0, idx - 200):idx + 600]
    assert "elem_classes" in nearby, \
        "限制页脚 Markdown 附近没有 elem_classes (无法加 margin-top 呼吸)"


def test_footer_margin_top_rule_exists():
    """tokens.css 有给页脚 margin-top 的规则 (页脚呼吸)。
    依赖上一条: 页脚 Markdown 带 elem_classes, 这里锁对应 CSS 块存在且有 margin-top。"""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    # 找一个含 margin-top 且明显是页脚/限制说明的规则。
    # 页脚类名可能是 .footer-notice / .limit-notice / .preset-footer 之类。
    # 宽松匹配: 任一选择器 + margin-top + 走 space token
    # 先找含 "footer" 或 "notice" 或 "limit" 的选择器
    footer_selectors = re.findall(r"\.(?:[\w-]*(?:footer|notice|limit)[\w-]*)\s*\{([^}]*)\}", text, re.S | re.I)
    found = False
    for body in footer_selectors:
        if "margin-top" in body:
            found = True
            break
    assert found, \
        "tokens.css 没有给页脚类 (.footer-notice 之类) 的 margin-top 规则 (页脚无呼吸)"
