# 排版精致化 TODO (2026-07-17)

> 对应审计: 2026-07-17 双 Explore agent (spacing/alignment + typography)
> 审计发现根因 3 类: token 不一致 / 视觉权重倒置 / 布局错位。
> 用户反馈: "各个地方的排版都很不精致"。

每条按 TDD:RED 写测试 -> 看 fail -> GREEN 改最小代码 -> 看 pass。
跑 `.venv\Scripts\python.exe -m pytest tests -q` 验证。

## 进度总览

| 组 | 项 | 状态 | 测试文件 |
| --- | --- | --- | --- |
| 1 | token 收敛 (字号 scale + 半径统一 + 内联硬编码) | DONE | tests/test_layout_polish_tokens.py |
| 2 | 视觉权重 (h3 提亮 + h2 提级 + 按钮字号拉开) | DONE | tests/test_layout_polish_hierarchy.py |
| 3 | 左右栏对齐 (equal_height + h2 margin) | DONE | tests/test_layout_polish_alignment.py |
| 4 | emoji baseline + textarea 行高 | DONE | tests/test_layout_polish_emoji.py |
| 5 | 页脚呼吸 + 按钮 padding 家族统一 | DONE | tests/test_layout_polish_spacing.py |
| 6 | 文字贴边修复 (container/nav-group/step-card padding) | DONE | tests/test_layout_polish_edge_padding.py |

执行顺序: 1 (基础) -> 2 (依赖 1) -> 3 -> 4 -> 5 -> 6。
最终: 523 passed / 9 skipped (baseline 497 -> +26 新增, 0 回归)。

## 每项详细记录

### 组 1 (DONE) — token 系统收敛

- RED: 4 tests fail (block_radius 12vs14 错位 / 内联 8px+硬编码颜色 / _DARK_SURFACE 死代码)。
- GREEN (app/static/tokens.css):
  - 字号 scale 删 `--text-md` (15px), lg 17→16; scale 收敛 12/13/14/16/20/24 (无 ≥3 连续 1px 步)。
  - `--radius-lg` 14→12, 跟 `THEME.block_radius="12px"` 统一 (消除全站 2px 圆角错位)。
- GREEN (app/scail2_app.py):
  - 删 `_DARK_SURFACE` 死代码常量 (定义了冲突的 `--text-faint: #5f6470`, 2.6:1 对比度)。
  - 内联 `border-radius:8px` (7 处) → `var(--radius-md)`; `color:#9ba1a8` → `var(--text-muted)`;
    `color:#6b7280` (8 处) → `var(--text-faint)`。共替换 16 处。
- Verify: 6 new tests pass + full suite 503 passed / 9 skipped.

### 组 2 (DONE) — 视觉权重层级

- RED: 2 tests fail (h3 用 --text-secondary 灰 / 工作流标题还是 ### h3)。
- GREEN:
  - tokens.css h3: `color: --text-secondary` → `--text-primary` (标题不再比 section header 暗)。
  - scail2_app.py: `### {display_name}` → `## {display_name}` (h2, 20px/600)。给清晰三级层级:
    h1=app, h2=workflow, section-header=form 小节。
  - tokens.css `.btn-run-primary`: font-size `--text-md` → `--text-lg` (16px), font-weight 600→700。
    (font-size 在组1 改, 这里补字重)
- Verify: 5 new tests pass + full suite 508 passed / 9 skipped.

### 组 3 (DONE) — 左右栏顶部对齐

- RED: 2 tests fail (equal_height=False / h2 顶部 margin --space-5 太大)。
- GREEN:
  - scail2_app.py: `with gr.Row(equal_height=False)` → `equal_height=True`。左右子栏等高,
    运行按钮锚定左栏底部, 不再随右栏 re_run_btn 出现而 Y 飘。
  - tokens.css h2: margin-top `--space-5` (20px) → `--space-3` (12px), 跟左栏 nav-group
    顶部基线对齐 (减少 ~8px 错位)。
- 锁定边界: 列 scale 4/7 不动 (test_e2e_render.py 锁)。
- Verify: 3 new tests pass + full suite 511 passed / 9 skipped.

### 组 4 (DONE) — emoji baseline + textarea 行高

- RED: 3 tests fail (无负值 vertical-align / textarea 无 line-height / leading 消费点 <3)。
- GREEN (tokens.css):
  - textarea 加 `line-height: var(--leading-normal) !important` (CJK 提示词不再挤)。
  - 新增 emoji baseline 规则: button/label/section-header/run-status-bar/h1/h2/h3 统一
    `line-height: --leading-normal` + `vertical-align: -0.15em`。修 Windows Segoe UI Emoji
    baseline 偏高 (🚀/📥/🔄 跟文字不齐)。
- Verify: 3 new tests pass + full suite 514 passed / 9 skipped.

### 组 5 (DONE) — 页脚呼吸 + 按钮 padding 家族统一

- RED: 3 tests fail (两按钮水平 padding 24vs20 / 页脚无 elem_classes / 无 footer CSS)。
- GREEN:
  - tokens.css `.btn-run-secondary` 水平 padding `--space-5` (20) → `--space-6` (24),
    跟 `.btn-run-primary` 统一 (同栏两按钮同宽, 靠颜色/字号区分主次)。
  - scail2_app.py: 限制说明页脚 Markdown 加 `elem_classes=["footer-notice"]`。
  - tokens.css 新增 `.footer-notice { margin-top: var(--space-3) }`, 给页脚跟 preset panel
    之间 12px 呼吸 (不动 `.preset-panels-host gap:0` 锁定)。
- UI_STYLE.md 注册 `.footer-notice` 类。
- Verify: 4 new tests pass + full suite 518 passed / 9 skipped.

### 组 6 (DONE) — 文字贴边修复

- 用户二次反馈: "导航、文生图 Z-Image-Turbo、输入素材 这些文字还是紧贴着边界"。
- RED: 3 tests fail (container/nav-group/step-card 都缺 padding)。
- GREEN (app/static/tokens.css):
  - `.gradio-container`: 加 `padding: var(--space-4) var(--space-5)` (整个应用内容
    左右各 ~16-20px 呼吸, 之前无 padding 直接贴浏览器窗口)。max-width 锁定保留。
  - `.nav-group`: `padding: 0` → `var(--space-3)` 四向 ("导航"标题 + 工作流列表不再贴 Group 边)。
  - `.step-card`: `padding: 0 0 var(--space-4) 0` → `var(--space-3) var(--space-3) var(--space-4) var(--space-3)`
    ("输入素材"标题 + 表单字段四向都有 12px, 底部 16px 拉开高级参数折叠区)。
- 测试 helper 增强: `_padding_values` 先 `_strip_comments` 去 CSS 注释, 防止
  注释里的字面 padding 值误导抽取 (注释提到旧值时不会被误抓)。
- Verify: 5 new tests pass + full suite 523 passed / 9 skipped.

---



## 测试契约边界 (探索确认, 不可越界)

- **列 scale 4/7 硬锁**: `test_e2e_render.py` 6 个 parametrize 测试锁 scale==4 / scale==7。**不动 scale**。
- **`.file-dropzone` / `.btn-secondary-override` 被测试锁存在性**: 不能删, 只改值。
- **`.run-status-progress` 必须在 `.run-status-elapsed` 之后**。
- **`--text-faint` 对比度 ≥ 3.8 且 < `--text-muted`**。
- **`.preset-panel` 不能有 min-height**; **`.preset-panels-host` gap 必须 = 0**。
- 可自由改: h3 字号/颜色、`.btn-run-primary` 字号字重、`THEME.block_radius`、`.section-header` 值、`equal_height`、min_width、标题层级。

## 审计发现的根因

### token 系统不一致
- 字号 scale: xs=12 / sm=13 / base=14 / md=15 / lg=17 → 13/14/15 三个 1px 步无区别。
- `THEME.block_radius="12px"` vs `--block-radius: var(--radius-lg)=14px` 全站 2px 错位。
- 内联硬编码: `border-radius:8px` (7 处)、`color:#9ba1a8`、`color:#6b7280` 绕过 token。
- `_DARK_SURFACE` 死代码常量定义了冲突的 `--text-faint: #5f6470` (2.6:1 对比度, 从未使用)。

### 视觉权重倒置
- h3 工作流标题 `color: --text-secondary` (灰 #c2c7d2), 下面 `**① 输入素材**` 用 `--text-primary` (白) → 副标题比标题醒目。
- `.btn-run-primary` 15px/600 vs secondary 14px/500 只差 1px+1 级。
- 工作流标题是 h3, 全局 h1→h3 跳过 h2, 层级断层。

### 布局对齐
- 左栏顶部 `**导航**` 小标签 vs 右栏 `###` H3 带 16px margin → 顶部错位 ~20px。
- `equal_height=False` → 运行按钮和输出区 Y 坐标飘 (首次成功后 re_run_btn 出现, 右栏长一截)。
- `.preset-panels-host gap:0` → 限制说明 `<small>` 贴着表单底部。
- emoji (Windows Segoe UI Emoji) baseline 偏高, 无 vertical-align 规则。
- textarea 无 line-height 声明, 继承 Gradio 默认 (CJK 提示词显挤)。

## 每项详细记录

(实施时按组回填 RED/GREEN 记录)
