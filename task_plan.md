# UI 深度重构计划

## 目标

- 永久移除历史记录相关产品路径、文档和样式残留。
- 把运行页重构为更像创意工作台的三段式界面：头部、导航、创作工作区。
- 解决“页面不够好看、层级混乱”的核心问题，而不是继续做零散补丁。

## 阶段

| 阶段 | 状态 | 内容 |
| --- | --- | --- |
| 1 | complete | 建立设计文档与规划文件，统一目标和边界 |
| 2 | complete | 清理历史记录相关残留：主文档、测试断言叙事 |
| 3 | complete | 重构运行页骨架：顶部头部、左侧导航、中间参数区、右侧结果区 |
| 4 | complete | 调整视觉层级与样式 token，压缩噪音、突出结果区 |
| 5 | complete | 跑测试与手动校验，修复回归 |
| 6 | complete | 结合 `apple-design` 审查整套工作台，产出全界面重构稿与独立 todo |
| 7 | complete | 按 `apple-design` 7 个 Phase 全部落地 (2026-07-20) |

## 关键决策

- `历史记录` 为永久放弃，不再保留“以后可能恢复”的叙事。
- 不更换 Gradio 技术栈，继续保留 schema 驱动表单。
- 深度重构优先于轻度美化，重点解决结构和层级，而不是只改颜色。

## 风险

- `scail2_app.py` 同时承担布局、状态、主题、事件，改动面较大。
- 旧文档和旧测试仍带有历史记录叙事，需同步清理，否则会制造伪回归。
- 预渲染 preset + `visible` 切换的机制必须保留，以免破坏表单状态保持。

## 本轮结果

- 已新增工作台头部、副标题和稳定骨架类名。
- 已把运行页基础区拆为 `输入素材 / 创作内容 / 输出规格 / 运行控制` 四段。
- 已为右侧结果区补上 `作品预览` 标题和更明确的舞台卡片。
- 已更新主文档，去掉主叙事中的历史记录入口说明。
- 已通过 164 个相关测试。

## 第二轮视觉打磨结果

- 已把应用头部升级为带 kicker 和状态 pills 的信息带。
- 已为导航补上说明文案，并把侧栏宽度提高到更适合中长 workflow 名称的比例。
- 已为结果区补上预览说明文案和统一动作工具条。
- 已清理 `tokens.css` 中历史页专属主样式区块。
- 已把工作台比例调整为 `左 5 / 右 6`，收紧主按钮与次按钮尺寸。
- 已通过第二轮相关回归测试，共 `169` 个。

## 第三轮设计沉淀结果

- 已安装并引入 `apple-design` skill 作为本轮审查方法论。
- 已从“只修头部”提升到“全界面材料、层级、反馈、文案系统”的整体重构视角。
- 已新增 `docs/plans/2026-07-18-apple-design-full-ui-redesign.md` 作为全界面重构总稿。
- 已新增 `docs/plans/2026-07-18-apple-design-full-ui-todo.md` 作为拆分后的执行清单。

## Phase 1 当前进展

- 已把头部从厚 Banner 压到更薄的 chrome 条带：减小 padding、降低阴影、降低署名权重。
- 已把左侧导航从重卡片材质压到更轻的磨砂结构层。
- 已把 `workflow-stage-header` 从大头卡改成紧凑标题行。
- 已把 `result-stage-card` 升格为更稳定的主舞台表面。
- 已补 4 条 Phase 1 新样式契约测试，并通过 `184` 个相关测试。
- 已用 `start_webui.bat` 重启后在浏览器实测，确认新材料层级已落到真实页面。

## Phase 2 当前进展

- 已为导航搜索框补 `nav-search-input` 钩子，并落地轻工具条样式。
- 已为系统状态补 `nav-system-status` 钩子，并把状态文字降到 meta 层级。
- 已把左侧工作流列表 hover / selected 从“位移卡片”收回到更克制的 source-list 语言。
- 已降低结果区 `作品预览` 标题和帮助文案的存在感，让右侧主舞台更直接。
- 已新增 Phase 2 样式契约测试，并通过 `189` 个相关测试。
- 已重启 WebUI 并在浏览器实测确认上述样式已真实生效。

## Phase 3 当前进展

- 已让导航与系统区从 divider 硬切改为同材质内过渡：`nav-divider` 隐藏，`nav-group-system` 走 top border 接续。
- 已把 `step-card` 的横向 padding 收回，输入区读感更接近连续工作台面。
- 已把默认 example、运行中、完成后结果统一到 `result-area-shell / result-area-media / result-area-caption / result-area-empty` 一套 wrapper。
- 已补对应的 helper / CSS 契约测试，并通过 `244` 个相关测试。
- 已重启 WebUI 并实测 `zimage / sca12_motion / sca12_replace / klein_edit / liveportrait` 五组 workflow，确认结果承载面统一生效。

## Phase 4 / 5 当前进展

- 已继续压低 `workflow-stage-header-subtitle`，把 preset 描述收回到 meta 层（`text-xs + muted + 44ch`）。
- 已把 `custom-accordion` 从强调色块改成更安静的 disclosure：去掉 accent 左边框，改为细 top border 接续。
- 已把 `run-status-bar` 从告警式提示条收回到更稳的状态层：磨砂背景、更薄高度、running 态不再脉冲。
- 已补相关样式契约测试，并通过 `122` 个中间区/状态层相关测试。
- 已重启 WebUI 并在浏览器里确认 subtitle / accordion / status layer 的 computed style 已真实生效。
- 已把中栏节奏梳理为 `① 输入参数 → ② 运行控制 → ③ 高级参数`，并把视频类 `预估段数` 收进运行控制段内部。
- 已为主按钮补更明确的 pointer-down 反馈，并为 workflow 切换 / 结果替换增加轻量淡入。
- 已为新增动效补 `prefers-reduced-motion` 降级，避免精致度和可访问性冲突。
- 已再次运行相关回归（`122 + 139` 条）并重启 WebUI，在新浏览器会话中确认 `zimage` 与 `sca12_replace` 的可见文本和顺序已真实更新。
- 已继续收敛标题下的 meta 文案：把偏长 preset 描述压到约 24 字以内，降低“标题区像第二段说明”的感觉。
- 已去掉文本类输入默认把 `help` 复写进 placeholder 的策略，减少首屏重复说明，同时保留 info 层提示。
- 已再次跑文案相关回归（`27 + 199` 条）并重启 WebUI，在浏览器确认 `zimage` 描述已收短、`sca12_replace` 的抠图提示词输入框不再重复显示同句 placeholder。
- 已推进 helper text 第二轮减法：把 `SCAIL2 / LivePortrait / qwen3_tts / ace_step_15_music` 的高频说明改成更短、更直接的任务文案。
- 已新增数据级 copy 契约测试并通过，同时继续通过 `112` 条与首屏结构/示例渲染相关的 UI 回归。
- 已重启 WebUI 并在新浏览器会话中确认：`sca12_replace`、`qwen3_tts`、`ace_step_15_music` 的首屏 helper 已按新文案显示。
- 已完成图片 / 视频 / 音频三类输出在新结果舞台中的第一轮一致性改造：三者都落到 `result-area-kind-*` + `result-area-asset` 结构，未知 fallback 也不再跳出结果舞台。
- 已把卡面语义统一收回 `.result-area-media`，并给音频结果单独设更紧凑的承载高度；相关契约测试与页面实测都已通过。
- 已再次重启 WebUI 并在浏览器量到：`image/video` 结果舞台为 `220px`，`audio` 结果舞台为 `160px`，与当前 Apple-like 工作台层级更一致。
- 已继续收敛结果区 copy：默认说明改成 `示例结果，运行后自动替换。`，页脚说明改成 `素材上限 · ...`，进一步降低教程感。
- 已把未知/降级 fallback 从告警式 banner 收成 quiet action row，并通过浏览器实测量到 `display:flex / align-items:center / rgba(255,255,255,0.02)`。

## 最终交付 (2026-07-20): apple-design 全界面重构全部落地

7 个 Phase 全部完成, 35/35 todo 项勾选。

### 本轮 (2026-07-20) 完成的剩余项

**B 类回归收口 (5 个 layout_polish 旧契约被 apple-design 重构吃掉)**
- `.step-card` 水平 padding=0 是 Phase 3 去横向包裹感契约, 字段呼吸改由父 `.preset-panel` padding 提供 → 同时满足两个互斥契约
- `.btn-run-primary` 字号恢复 `--text-lg`
- 两按钮水平 padding 统一到 `--space-5`
- textarea `line-height: var(--leading-normal)` (修测试正则的脆弱写法)
- 页脚文案断言跟着 `限制:` → `素材上限 ·` 更新

**SKILL §14 三套 accessibility 媒体查询完整**
- 新增 `@media (prefers-reduced-transparency: reduce)` —— 三层磨砂面关 backdrop-filter
- 新增 `@media (prefers-contrast: more)` —— 磨砂面 + 输入框 + 结果区加 1px 明确边界
- 加 `test_prefers_reduced_transparency_disables_backdrop_filter` / `test_prefers_contrast_more_adds_explicit_borders` 锁

**Phase 1/2 收尾**
- 头部高对比/reduced-transparency 兼容 (由 §14 媒体查询覆盖)
- `.custom-radio label span` 从 `nowrap+ellipsis` 改 `word-break:break-word` —— 28 字长名不再截断

**Phase 3 收尾**
- 全部 spec 显式 tier (zimage / qwen_image_2512_4step / klein_edit 8 个之前漏的 spec 补全)
- `ltx_23_t2v_distill` / `qwen_image_2512_4step` advanced 字段错位 (插在 basic 中间) 修正
- 最后一个解释腔 helper "告诉模型要改什么" 删除
- 新增 `test_field_order_basic_before_advanced` / `test_field_tier_always_explicit` 锁

**Phase 5 收尾**
- accordion `.label-wrap` 加 `transition: color ease-out`; 箭头加 `transition: transform ease-spring`
- 新增 `_failure_hint(msg)` 按错误关键词 (upload/queue/timeout/patch/cuda/file-size) 给下一步建议
- `.run-status-hint` quiet meta row (flex-basis:100% 换到 status-bar 第二行)
- 加 4 条测试锁 5 类错误的 hint + accordion 过渡 + hint 样式

**Phase 6 整块**
- 砍掉导航 `.nav-rail-note` "选择一个预置工作流后..." 结构性解释句 + 对应 CSS class
- 砍掉主题 tab "新增主题编辑 themes.json" dev hint (用户视角不该看到内部文件名)
- 四级标题层级已完整 (h1=2xl/700, h2=xl/600, h3=lg/600, section-header=base/600, app-shell-title=display 级)
- 字重/字号/tracking/leading token 体系审计完成 (七档 size + 三档 leading + tracking 只在 display 级用负值)
- 诗句字体复核: 保留 KaiTi/STKaiti + fallback sans, AGENTS.md 已记录"局部例外"

**Phase 7 验收**
- `UI_STYLE.md` 同步: §1.1 三层材料系统, §1.2 三套媒体查询, §4 补 11 个新 class, §6.1 三段节奏契约
- 10 个 preset 全部 `_render_workflow_form` 渲染 OK
- 全量回归 `pytest tests/ -q` = **594 passed / 9 skipped / 0 failed** (从本轮起点的 12 failed 收口)
- 浏览器实测: 服务端 page.html 内联 CSS blob 11 项关键规则全部 verified

### 范围声明

apple-design SKILL.md 17 章里, §2/§3/§5/§6/§8/§9/§10 (手势/中断/动量/橡胶带) 依赖 Pointer Events + JS spring library, Gradio Python-driven 表单不适合, 显式不做。§13 (sound/haptics) Web 上价值低, 显式不做。详见 `docs/plans/2026-07-18-apple-design-full-ui-todo.md` 末尾"范围声明"。
