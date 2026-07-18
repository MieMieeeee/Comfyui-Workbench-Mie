"""排版精致化 组1: token 系统收敛测试。

审计发现:
- 字号 scale 有 13/14/15 三个 1px 步 (sm/base/md), 视觉无区别。
- THEME.block_radius=12 vs --block-radius=14 全站 2px 错位。
- 内联硬编码 border-radius:8px / color:#9ba1a8 / color:#6b7280 绕过 token。

收敛方向:
- 字号 scale: 删 --text-md, lg 从 17→16, scale 变 12/13/14/16/20/24 (≥2px 跨步)。
- 半径: --radius-lg 14→12, 跟 THEME.block_radius=12 统一。
- 内联值全走 token。
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


def _extract_root_block(text: str) -> str:
    """提取第一个非空的 :root {} 块 (跳过注释里字面的 :root{})。"""
    for m in re.finditer(r":root\s*\{([^}]*)\}", text, re.S):
        body = m.group(1)
        if len(body) > 50:  # 真实 token 块 >3k 字符; 注释里的字面 :root{} 是空的
            return body
    return ""


def _token_value(root_body: str, name: str) -> int | None:
    m = re.search(rf"--{re.escape(name)}:\s*(\d+)px", root_body)
    return int(m.group(1)) if m else None


# --- 字号 scale 无 1px 连续步 ---

def test_text_scale_has_no_three_adjacent_1px_steps():
    """字号 scale 不能有 >=3 个连续 1px 步 (13/14/15 这种无区别的三步)。
    允许至多 2 个连续 1px 步 (12/13/14 这种, sm 给辅助文字用, 有意义)。
    审计发现的原问题: 13/14/15/17 四个相邻步里前三个都只差 1px (max_run=3)。"""
    root = _extract_root_block(TOKENS_CSS.read_text(encoding="utf-8"))
    sizes = []
    for name in ("text-xs", "text-sm", "text-base", "text-md", "text-lg", "text-xl", "text-2xl"):
        v = _token_value(root, name)
        if v is not None:
            sizes.append(v)
    diffs = [sizes[i+1] - sizes[i] for i in range(len(sizes) - 1)]
    # 连续 1px 步不能 >= 3 (即 max_run < 3)
    max_run = 0
    cur = 0
    for d in diffs:
        if d == 1:
            cur += 1
            max_run = max(max_run, cur)
        else:
            cur = 0
    assert max_run < 3, \
        f"字号 scale 有连续 {max_run+1} 个 1px 步 (sizes={sizes}, diffs={diffs}); " \
        f"13/14/15 这种三步无区别, 应收敛"


def test_text_md_token_removed_or_merged():
    """--text-md (15px) 应该被删掉或并入 base。
    审计: 13/14/15 三步无区别, md 是多余的。消费点 (btn-run-primary / section-header)
    在组2 改成 --text-lg / --text-base。这里只锁 token 定义层: md 要么不存在,
    要么值跟 base 一样 (不再制造独立的 15px)。"""
    root = _extract_root_block(TOKENS_CSS.read_text(encoding="utf-8"))
    md = _token_value(root, "text-md")
    base = _token_value(root, "text-base")
    if md is not None:
        # md 还在 -> 必须跟 base 同值 (不再制造 15px 独立步)
        assert md == base, \
            f"--text-md={md}px 跟 --text-base={base}px 不同, 制造了无意义的 1px 步"


# --- block_radius 统一 ---

def test_block_radius_matches_theme_block_radius():
    """THEME.block_radius 必须等于 --block-radius token (或 --radius-lg) 值。
    审计: THEME=12px vs token=14px 全站 2px 错位, 每个 Gradio 原生块跟自定义卡
    圆角不一致 -> "不精致" 的主要来源。"""
    # 从 tokens.css 读 --radius-lg (block-radius = radius-lg)
    root = _extract_root_block(TOKENS_CSS.read_text(encoding="utf-8"))
    radius_lg = _token_value(root, "radius-lg")
    assert radius_lg is not None, "缺 --radius-lg"
    # THEME.block_radius 是字符串如 "12px"
    theme_radius = scail2_app.THEME.block_radius if hasattr(scail2_app.THEME, "block_radius") else None
    assert theme_radius is not None, "THEME 无 block_radius 属性"
    theme_px = int(re.search(r"\d+", str(theme_radius)).group(0))
    assert theme_px == radius_lg, \
        f"THEME.block_radius={theme_px}px != --radius-lg={radius_lg}px (全站圆角错位)"


# --- 内联硬编码 ---

def test_no_inline_border_radius_8px_in_media_html():
    """_media_to_html 产生的 HTML 不再用字面 border-radius:8px (走 token)。
    8px 不在任何 token scale 里 (有 6/10/14), 跟容器圆角不一致。"""
    import inspect
    src = inspect.getsource(scail2_app._media_to_html)
    assert "border-radius:8px" not in src and "border-radius: 8px" not in src, \
        "_media_to_html 还有字面 border-radius:8px, 应走 var(--radius-md)"


def test_no_inline_hardcoded_color_in_description_render():
    """_render_workflow_form 的工作流描述不用字面 #9ba1a8 (走 var(--text-muted))。
    #9ba1a8 不在任何 --text-* token 里 (muted=#8b909b, faint=#767c8a), 脱离调色板。"""
    import inspect
    src = inspect.getsource(scail2_app._render_workflow_form)
    assert "#9ba1a8" not in src, \
        "_render_workflow_form 还有字面颜色 #9ba1a8, 应走 var(--text-muted)"


def test_dark_surface_dead_constant_removed():
    """_DARK_SURFACE 死代码常量应删除。
    审计: 它定义了冲突的 --text-faint: #5f6470 (2.6:1 对比度, 从未使用),
    若未来误接会让 faint 文字跌破 WCAG。"""
    assert not hasattr(scail2_app, "_DARK_SURFACE"), \
        "_DARK_SURFACE 死代码常量还在 (定义了冲突的 --text-faint: #5f6470)"
