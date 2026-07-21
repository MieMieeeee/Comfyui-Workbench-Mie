# TODO — Web Design Guidelines 合规整改 (2026-07-21) ✅ 完成

> 评审依据: Vercel Web Interface Guidelines
> (https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md)
>
> 评审目标: `app/scail2_app.py` + `app/static/tokens.css`
> 评审方式: TDD — 先写失败测试 (RED), 再改代码到 GREEN.
> 每条 fix 对应 tests/test_web_design_guidelines.py 里的一个或多个 case.
>
> **最终状态 (Round 1 + Round 2)**:
>   - **20/20 guideline 测试 GREEN**, 完整回归 **534 passed**, 3 skipped, 0 failed
>   - Vercel Web Interface Guidelines **所有适用规则全部合规**
>   - 剩余规则 N/A 清单见底部 "不再追究的项" —— 都不是 TDD 推进失败, 而是规则前提
>     在本项目根本不存在 (无 modal / 无 web font / 无时间戳 UI / 无 above-fold 图 /
>     项目不写前端 JS / Gradio 6 框架限制 + AGENTS.md data-driven 原则)

## 整改项 (按优先级)

### P0 — Hard requirement, 反模式 (必改) ✅

- [x] **CSS-001** `tokens.css:266` `.btn-secondary-override` `transition: all` → `background, border-color, color`
- [x] **CSS-002** `tokens.css:1024` `.custom-radio label` `transition: all` → `background, border-color, border-left-color, color`
- [x] **CSS-003** `tokens.css:1299` `.file-dropzone` `transition: all !important` → `background, border-color, color, box-shadow`
  - 测试: `test_tokens_css_has_no_transition_all`

### P1 — 明确要求, 影响 a11y / UX (必改) ✅

- [x] **TYPE-001** 进度文案 ASCII `...` → Unicode `…` (U+2026)
  - 共修 19 处: 9 处 `progress(..., desc="...")` + 10 处 `yield "..."`
  - 测试: `test_no_ascii_ellipsis_in_yield_or_progress_strings`
- [x] **IMG-001** `<img>` 缺 `width`/`height` → 加 `width="100%" height="auto"` (CLS)
  - 测试: `test_media_to_html_single_image_has_width_height` + grid + video-context
- [x] **IMG-002** `<img>` below-fold 缺 `loading="lazy"` → 已加
  - 测试: `test_media_to_html_single_image_has_loading_lazy`
- [x] **VID-001** `<video>` 缺 `width`/`height` + `preload` → 加 `preload="metadata"`
  - 测试: `test_media_to_html_video_has_width_height` + `test_media_to_html_video_has_preload_metadata`
  - 额外修了 preset preview 的 `<video>` / `<img>` (一致性, 非测试覆盖但同源问题)

### P2 — 规则要求, 影响键盘 a11y / 暗模式 (建议改) ✅

- [x] **FOCUS-001** `:focus` → `:focus-visible` (避免点击后留 focus ring)
  - `tokens.css` input/textarea 两处已改
  - 测试: `test_input_focus_rules_use_focus_visible`
- [x] **DARK-001** `:root` 缺 `color-scheme: dark` → 已加
  - 测试: `test_tokens_css_declares_color_scheme_dark`

### P3 — Touch / form 细节 (建议改) ✅

- [x] **TOUCH-001** `body` 加 `touch-action: manipulation`
  - 测试: `test_tokens_css_sets_touch_action_manipulation`
- [x] **TOUCH-002** `body` 加 `-webkit-tap-highlight-color: transparent`
  - 测试: `test_tokens_css_sets_tap_highlight_color`
- [x] **FORM-001** ComfyUI URL Textbox 加 `html_attributes={"autocomplete": "off"}`
  - 注: Gradio 6.20 的 Textbox 没有 top-level autocomplete 参数, 走 `html_attributes` 透传
  - 测试: `test_settings_url_input_has_autocomplete_off`

### P3 — 按钮文案 review (defer) ⏸

- [x] **BTN-001** 现有 label 已 specific, 不需再改
  - 规则原意: 反对 "Continue" / "Submit" 这类无信息量 label
  - 当前所有按钮 (`🚀 开始运行` / `📥 加载示例素材` / `📂 加载上次成功参数` /
    `🎲 随机提示词` / `🔍 完整健康检查` / `🔄 刷新状态` / `保存并测试` 等)
    都明确说明动作 + 对象, 已符合规则精神
  - 决定: 不动, 避免不必要的 UI churn

### 已合规 (本轮不动) ✅

- `user-scalable=no` / `maximum-scale=1` — 未使用
- `onPaste preventDefault` — 未使用
- `<div onClick>` 反模式 — 未使用
- `autoFocus` — 未使用
- `prefers-reduced-motion` / `prefers-reduced-transparency` / `prefers-contrast: more` 三套 a11y 媒体查询齐全
- 动效只动 `transform` / `opacity` / `box-shadow`
- `.run-status-msg` 有 `text-overflow: ellipsis` + `min-width: 0`
- empty state (`_result_area_empty_html`) 存在

## 执行记录

1. ✅ 新建 `tests/test_web_design_guidelines.py` (13 个 case), 跑一次确认 RED
2. ✅ 调整 2 个 test 的边界 (跳过 CSS 注释 / 精化 loading-state 语境):
   - `test_tokens_css_has_no_transition_all` 不扫注释 (否则自己的规则说明注释会误命中)
   - `test_no_ascii_ellipsis_in_yield_or_progress_strings` 只扫 `desc=` / `yield` 行
     (Python 3 `re` 默认 unicode, `\w` 匹配中文, 原 `(?<![.\w])` 会把 "准备中..." 错排除)
3. ✅ 按优先级修代码 (P0 → P1 → P2 → P3), 每组跑对应测试确认 GREEN
4. ✅ 完整 `pytest tests -q`: **527 passed, 3 skipped, 0 failed**
5. ✅ e2e render + theme: **80 passed, 3 skipped**

## 不在本轮范围 (下一轮考虑) — Round 2 后更新

| 项 | Round 2 处置 | 理由 |
|---|---|---|
| `<meta name="theme-color">` | ✅ **Round 2 已修** | Gradio 6 `launch(head=...)` 支持, 引入 `_build_launch_head()` helper |
| `env(safe-area-inset-*)` | ✅ **Round 2 已修** | CSS 层加在最外层 `.gradio-container`, 可单元锁规则存在 |
| `overscroll-behavior: contain` | ❌ **N/A 永久跳过** | grep `gr.Modal / gr.Dialog` 全空 — 项目无任何自建 modal / drawer / sheet, 规则不适用 |
| `Intl.DateTimeFormat / NumberFormat` | ❌ **N/A 永久跳过** | history tab 已被移除 (`scail2_app.py:1656` 注释 "replaces the removed history tab"), 当前 UI 无任何时间戳 / 数字格式化显示 |

## Round 2 — 上一轮 "不在范围" 里现在能 TDD 推进的项 ✅

### R2-META-001  `<meta name="theme-color">` + `<meta name="color-scheme">`

- [x] 引入模块级 `_build_launch_head()` helper (对称 `_build_launch_css()`)
- [x] 返回 `<meta name="theme-color" content="#0f1115">` + `<meta name="color-scheme" content="dark">`
- [x] theme-color 值与 tokens.css `--bg-app` 一致 (锁同一常量 `_PAGE_BG_COLOR = "#0f1115"`)
- [x] `launch(head=HEAD)` 注入 (HEAD 模块常量, 紧跟 CSS = ...)
- 测试: 5 个 case
  - `test_build_launch_head_helper_exists`
  - `test_build_launch_head_contains_theme_color_meta`
  - `test_build_launch_head_theme_color_matches_bg_app_token` (锁 token 一致)
  - `test_build_launch_head_includes_color_scheme_meta`
  - `test_launch_call_uses_head_param` (grep demo.launch block)

**为什么两道声明 (CSS `:root` + HTML `<meta>`)**:
- `<meta name="color-scheme">` 让浏览器在 CSS 解析前就用 dark variant → 避免首屏 FOUC (白底一闪)
- `:root { color-scheme: dark }` 是 CSS 层的强声明, 优先级更高 (覆盖 meta)
- 两者不冲突, 是双保险

### R2-SAFE-001  `env(safe-area-inset-*)` on `.gradio-container`

- [x] `.gradio-container` padding 改用 `calc(var(--space-x) + env(safe-area-inset-*))`
- [x] 四向分别计算 (top/right/bottom/left), 因为 notch / island 只在一两个方向
- [x] 加在最外层容器, 不加内层卡片 (否则双重缩进)
- 测试: 2 个 case
  - `test_tokens_css_uses_safe_area_inset`
  - `test_safe_area_applied_to_outermost_container` (锁只加在 body/html/.gradio-container)

**fallback 行为**: 不支持 `env()` 的旧浏览器 (Chrome < 69 / Safari < 11.1) `calc()` 中的 `env()` 求值为空, 自动退化为 `calc(var(--space-x))` = 原 padding. 不会破坏现有布局.



## 修改清单 (供 commit reference)

```
=== Round 1 ===

app/static/tokens.css
  + :root { color-scheme: dark; ... }
  + body { touch-action: manipulation; -webkit-tap-highlight-color: transparent; }
  ~ .btn-secondary-override: transition: all → 列属性
  ~ .custom-radio label:        transition: all → 列属性
  ~ .file-dropzone:             transition: all !important → 列属性
  ~ input/textarea :focus → :focus-visible

app/scail2_app.py
  ~ _media_to_html: <img>/<video> 加 width/height/loading/preload (5+2 处)
  ~ preset preview 的 <img>/<video> 同步加 (2 处)
  ~ 19 处 loading-state 字符串 ASCII "..." → Unicode "…"
  ~ settings tab URL Textbox 加 html_attributes={"autocomplete": "off"}

tests/test_web_design_guidelines.py  (新增, 13 case)
docs/TODO_WEB_DESIGN_GUIDELINES_2026-07-21.md  (本文件)

=== Round 2 ===

app/static/tokens.css
  ~ .gradio-container padding: 改 calc() 叠加 env(safe-area-inset-*)

app/scail2_app.py
  + _PAGE_BG_COLOR 常量 (= "#0f1115", 与 --bg-app 同步)
  + _build_launch_head() helper (生成 theme-color + color-scheme meta)
  + HEAD 模块常量 (紧跟 CSS = ...)
  ~ main() demo.launch(...) 加 head=HEAD 参数

tests/test_web_design_guidelines.py  (+7 case, 累计 20)
docs/TODO_WEB_DESIGN_GUIDELINES_2026-07-21.md  (Round 2 段落更新)
```

## 测试统计

| 阶段 | test_web_design_guidelines.py | 全量回归 |
|---|---|---|
| Round 1 完成 | 13 passed | 527 passed, 3 skipped |
| Round 2 完成 | **20 passed** | **534 passed**, 3 skipped |
| e2e render + theme | — | 80 passed, 3 skipped |

## 不再追究的项 (N/A 永久跳过)

### Trust model / 框架限制类 N/A (规则前提不存在)

- **`overscroll-behavior: contain`** — grep `gr.Modal / gr.Dialog` 全空, 项目无任何自建
  modal / drawer / sheet. Gradio 原生组件的滚动隔离由框架管. 未来若加 `gr.Modal` 再评估.
- **`Intl.DateTimeFormat / NumberFormat`** — history tab 已被移除
  (`scail2_app.py:1656` 注释 "replaces the removed history tab"), UI 无任何时间戳 /
  数字格式化显示. 未来若恢复 history tab 或 status bar 显示时间, 再用 `Intl.*`.

### Performance / 资源加载类 N/A (项目无对应资源)

- **List virtualization (`virtua` / `content-visibility`)** — 只有 10 个 preset, 远低于
  规则的 ">50 items 才需 virtualize" 阈值. 静态 gr.Radio 已足够.
- **`<link rel="preconnect">` for CDN** — tokens.css 的 `--font-sans` 全用系统字体
  (`-apple-system, Segoe UI Variable, PingFang SC, Microsoft YaHei UI, system-ui`),
  无 Google Fonts / CDN 字体. 无外部域可 preconnect.
- **`<link rel="preload" as="font">` with `font-display: swap`** — 同上, 无 web font
  需要预加载.
- **Critical `<img>` priority / fetchpriority** — 项目所有 `<img>` 都是 ComfyUI 生成结果图,
  全在 below-fold, 已统一 `loading="lazy"`. 无 above-fold critical image 需要 priority.
- **Layout thrash (`getBoundingClientRect` in render)** — 项目**不写前端 JS** (纯 Gradio
  后端 + Python). grep `getBoundingClientRect / offsetHeight / scrollTop / addEventListener`
  全空. 这条规则针对 React 渲染循环里的反模式, 对我们 N/A.

### Navigation & State 类 N/A (框架限制 + 项目原则) — 用户决策 2026-07-21

- **URL reflects tab state (deep-link tabs via query params)** — 项目有 `gr.Tabs`
  (运行 / 系统设置, `scail2_app.py:2454-2628`), 但 Gradio 6 的 `gr.Tabs` **不暴露
  tab → URL 同步 API**. 三种处置:
  1. 永久 N/A (本次采用)
  2. 调研 Gradio 6 deep_link / link_to_tab 原生参数
  3. `launch(js=...)` 注入自定义同步脚本
  用户选定方案 1: Gradio 6 框架本身不暴露该 API, 方案 3 需要写自定义 JS 注入, 违背
  AGENTS.md "data-driven, no new code" 原则. 跟 overscroll / Intl 同等处置.
  未来若 Gradio 原生支持 deep_link, 再回来评估.



