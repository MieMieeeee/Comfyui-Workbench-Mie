"""E2E 浏览器主题切换测试 —— 切主题后原生 primary 按钮背景色跟着变。

回归锁定 2026-07 用户报告:\"有些主题变了 有些没有 甚至是系统设置里自己的按钮颜色都没变\"。
排查发现:Gradio 的 --button-primary-background-fill 写死 orange,切主题不会变。
修复见 app/static/tokens.css 的 :root.dark{} 覆盖块。
单元测试只验 CSS 文本,本 E2E 在真实浏览器里加载页面、切主题、读 computed style,
确认原生 primary 按钮的背景色真的跟着变。

默认不跑(需 --e2e): pytest --e2e tests/test_e2e_theme_native_buttons.py
前置: pip install -r requirements-dev.txt && playwright install chromium
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# fixture: page, gradio_server, browser 来自 conftest.py


pytestmark = pytest.mark.e2e


# 主题 RGB 期望值 —— 从 app/presets/themes.json 的 --theme-accent-500 推算
# coral-orange: #ff6347 → rgb(255, 99, 71)
# cyber-blue:   #056681 → rgb(5, 102, 129)
# 两个差异足够大,任何一个切对了都能区分。
EXPECTED_PRIMARY_RGB = {
    "coral-orange": "rgb(255, 99, 71)",
    "cyber-blue":   "rgb(5, 102, 129)",
}


def _find_primary_save_btn(page):
    """在系统设置 tab 里找 \"保存并测试\"(纯 variant=\"primary\",无 elem_classes)
    按钮 —— 这是用户报\"按钮颜色没变\"的具体目标。
    """
    pg, base_url = page
    # 先切到 \"系统设置\" tab
    clicked = pg.evaluate("""() => {
        const tabs = document.querySelectorAll('[role="tab"]');
        for (const t of tabs) {
            if (t.textContent.trim() === '系统设置') { t.click(); return true; }
        }
        return false;
    }""")
    assert clicked, "找不到 '系统设置' tab,UI 渲染失败"
    time.sleep(0.6)  # 等 tab 切换 + 内容渲染

    info = pg.evaluate("""() => {
        for (const b of document.querySelectorAll('button')) {
            if (b.textContent.trim() === '保存并测试') {
                const cs = getComputedStyle(b);
                return {
                    bg: cs.backgroundColor,
                    bgImage: cs.backgroundImage,
                    cls: (b.className || '').toString().slice(0, 200),
                };
            }
        }
        return null;
    }""")
    return info


def _select_theme(page, theme_id: str):
    """点击主题 radio 选中 theme_id 对应的 option。
    Gradio 的 gr.Radio 把 value 放在 input.value 属性,直接 r.value === themeId 匹配。
    """
    pg, base_url = page
    js = '(themeId) => { const rs=document.querySelectorAll("input[type=radio]"); for(const r of rs){ if(r.value===themeId){ r.click(); return true; } } return false; }'
    clicked = pg.evaluate(js, theme_id)
    if not clicked:
        pytest.skip(f"找不到 theme_id={theme_id} 对应的 radio option")
    time.sleep(0.8)  # 等 Gradio 推 <style>:root{} 上去 + CSS 级联


def test_theme_switch_changes_native_primary_button_color(page):
    """切主题后,纯 variant=primary 的 \"保存并测试\" 按钮背景色跟着变。

    之前是 #f97316 (Gradio Soft 的 orange_500) 锁死,切主题不变。
    修复后跟着 --theme-accent-500 走:coronal-orange = #ff6347, cyber-blue = #056681。
    """
    pg, base_url = page
    pg.goto(base_url, wait_until="networkidle", timeout=20000)
    time.sleep(1.5)

    # 1. 切到系统设置 tab
    initial = _find_primary_save_btn(page)
    assert initial is not None, "找不到 '保存并测试' primary 按钮"
    initial_bg = initial["bg"]
    print(f"coral-orange primary bg = {initial_bg}")

    # 2. 切到 cyber-blue 主题
    _select_theme(page, "cyber-blue")

    after = _find_primary_save_btn(page)
    after_bg = after["bg"]
    print(f"cyber-blue primary bg = {after_bg}")

    # 3. 两个主题下颜色必须不同(且都不应是 Gradio 默认的 #f97316)
    assert initial_bg != after_bg, (
        f"切主题后 primary 按钮背景色没变 ({initial_bg}),"
        "2026-07 用户报告的 bug 复现了 —— tokens.css 的 :root.dark 覆盖失效"
    )
    # 切到 cyber-blue 后应该接近 #056681,不应还是 #f97316 (orange) 或 #ff6347 (coral)
    EXPECTED_BLUE = "rgb(5, 102, 129)"
    EXPECTED_CORAL = "rgb(255, 99, 71)"
    assert after_bg == EXPECTED_BLUE, (
        f"切到 cyber-blue 后 primary 按钮背景应该是 {EXPECTED_BLUE},"
        f"实际 {after_bg} —— 覆盖没生效"
    )
    assert initial_bg == EXPECTED_CORAL, (
        f"coral-orange 下 primary 按钮背景应该是 {EXPECTED_CORAL},"
        f"实际 {initial_bg} —— 覆盖没生效"
    )


def test_theme_switch_persists_after_navigation(page):
    """切到 cyber-blue → 跳回 \"运行\" tab → 再回到 \"系统设置\" tab → 颜色仍是 cyber-blue。

    锁定 theme_injector 持久性:之前 fixed_patches 也曾因 injector 重置把
    主题状态打回默认,这条测试防同样问题。
    """
    pg, base_url = page
    pg.goto(base_url, wait_until="networkidle", timeout=20000)
    time.sleep(1.5)

    # 先切到系统设置 tab,主题 radio 在那
    _find_primary_save_btn(page)  # 这一步顺带切到系统设置 tab

    # 切主题
    _select_theme(page, "cyber-blue")
    after_change = _find_primary_save_btn(page)
    assert after_change["bg"] == "rgb(5, 102, 129)", \
        "切到 cyber-blue 后 background 应立刻是 #056681"

    # 跳回 \"运行\" tab
    pg.evaluate("""() => {
        const tabs = document.querySelectorAll('[role="tab"]');
        for (const t of tabs) {
            if (t.textContent.trim() === '运行') { t.click(); return; }
        }
    }""")
    time.sleep(0.5)

    # 再回 \"系统设置\"
    again = _find_primary_save_btn(page)
    assert again["bg"] == "rgb(5, 102, 129)", (
        "切回运行 tab 再回设置 tab,primary 按钮颜色应该仍是 cyber-blue,"
        f"实际 {again['bg']} —— theme_injector 状态可能丢失"
    )


def test_run_btn_has_is_running_class_no_run_needed(page):
    """点击 \"开始运行\" 后按钮进入 .is-running 态(文本 \"⏳ 正在运行…\" + spinner)。

    走真实 ComfyUI 启动 + 跑一次 SCAIL2 不现实 —— 这里改成\"短按\"测样式:
    用 JS 临时给 run_btn 加 .is-running 类(模拟运行中态),验证 CSS 真的让
    按钮显示 pulse + spinner ::before。验证两个不变量:
      1. CSS 里有 .btn-run-primary.is-running 选择器(单元测试已覆盖,这里 E2E 验证效果)
      2. .is-running 加上后 computed animation 真的非空

    这是 fallback —— 真正的\"运行时\"路径需要 ComfyUI + 慢工作流,留给后续测试。
    """
    pg, base_url = page
    pg.goto(base_url, wait_until="networkidle", timeout=20000)
    time.sleep(1.5)

    info = pg.evaluate("""() => {
        const btns = document.querySelectorAll('.btn-run-primary');
        for (const b of btns) {
            if (b.textContent.includes('开始运行')) {
                // 临时加 .is-running 类,验证 CSS 效果
                b.classList.add('is-running');
                const cs = getComputedStyle(b);
                const csBefore = getComputedStyle(b, '::before');
                const result = {
                    animation: cs.animation || cs.animationName,
                    cursor: cs.cursor,
                    hasIsRunning: b.classList.contains('is-running'),
                    beforeContent: csBefore.content,
                    beforeAnimation: csBefore.animation || csBefore.animationName,
                    beforeBorderRadius: csBefore.borderRadius,
                };
                // 测完恢复
                b.classList.remove('is-running');
                return result;
            }
        }
        return null;
    }""")
    assert info is not None, "找不到 .btn-run-primary '开始运行' 按钮"
    assert info["hasIsRunning"], "JS 加 class 失败,浏览器 API 出错"
    # .is-running 应该让 animation 不为空(脉冲动画)
    assert info["animation"] not in ("", "none"), (
        f".is-running 态下 animation 应该是 pulse 动画,实际 {info['animation']!r}"
    )
    # ::before 应该渲染圆形 spinner(border-radius: 50% + 旋转 animation)
    assert info["beforeBorderRadius"] == "50%", (
        f"::before 的 spinner 应该是圆形 border-radius=50%,"
        f"实际 {info['beforeBorderRadius']!r}"
    )
    assert info["beforeContent"] not in ("none", "", "normal"), (
        f"::before 应该有 content(空字符串也行,只要不是 none),"
        f"实际 {info['beforeContent']!r}"
    )
