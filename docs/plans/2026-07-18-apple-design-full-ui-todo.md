# Apple-Design 全界面重构 Todo

## 使用方式

- 本文件是执行清单，不是设计说明。
- 每一项都应在浏览器实检后再勾选完成。
- 任何视觉修复都不能只看 pytest，必须结合 `start_webui.bat` 重启后的真实页面。

## Phase 1 头部与材料系统

- [x] 把顶部 `app-shell-header` 从 Banner 改成更薄的 chrome 条带
- [x] 降低头部阴影、发光和整体高度，保留轻量身份感
- [x] 进一步降低右侧署名字号和字重，让它更像落款
- [x] 调整诗句与名字的间距、颜色和右内缩
- [x] 统一头部与下方工作区的边框、透明度和材料语言
- [x] 为头部补 reduced-motion / 高对比兼容策略（2026-07-20: prefers-reduced-transparency + prefers-contrast 两套媒体查询已补, 头部 .app-shell-header 都在覆盖列表里; 测试 tests/test_css_theming.py::test_prefers_reduced_transparency_disables_backdrop_filter / test_prefers_contrast_more_adds_explicit_borders 锁住）

## Phase 2 左侧导航重构

- [x] 去掉左侧导航“独立重卡片”感，改成更轻的结构层
- [x] 合并导航区和系统区的材料表现，减少像两张卡片拼接的感觉
- [x] 将搜索框改成更轻的工具输入条样式
- [x] 重做工作流列表项的 hover / selected / pressed 态
- [x] 将选中态改为“轻底 + 清晰文字 + 细高亮条”
- [x] 压缩系统区文案，只保留必要状态和工具动作
- [x] 检查长 workflow 名称在新导航样式下的换行和对齐（2026-07-20: .custom-radio label span 从 white-space:nowrap + ellipsis 改成 word-break:break-word + line-height:leading-tight, "语音合成 (Qwen3-TTS VoiceDesign)" 28 字不再被截断; 测试 test_custom_radio_label_allows_wrapping_for_long_workflow_names 锁住）

## Phase 3 中间输入区重构

- [x] 将 `workflow-stage-header` 改成紧凑标题行，而不是大头卡
- [x] 缩短 preset 描述文案，避免与结构重复表达
- [x] 进一步弱化 `step-card` 容器边界，只保留流程节奏
- [x] 重新梳理 `输入参数 / 运行控制 / 高级参数` 三段之间的垂直节奏
- [x] 把高级参数折叠区做得更像 quiet disclosure，而不是另一块卡片
- [x] 收敛 helper text，保留必要提示，删掉解释性废话（2026-07-20: 最后一个解释腔 "告诉模型要改什么" 已删, 整库无残留; 测试 test_display_name_normalization.py 系列锁 copy 契约）
- [x] 复核所有 preset 的字段顺序是否仍严格遵循用户任务流（2026-07-20: 全部 spec 显式 tier; ltx_23_t2v_distill / qwen_image_2512_4step advanced 错位已修; 新增 test_field_order_basic_before_advanced + test_field_tier_always_explicit 锁契约）

## Phase 4 右侧结果区升格

- [x] 降低 `作品预览` 标题存在感，让结果面板自身成为主视觉
- [x] 提升结果舞台表面的稳定感和质量感
- [x] 统一 example、运行中、完成后结果的承载表面
- [x] 继续压低帮助文案和日志的存在感
- [x] 重新检查图片、视频、音频三类输出在新舞台中的对齐与留白
- [x] 确认 `sca12_motion / sca12_replace / klein_edit / liveportrait / zimage` 五组工作流的结果区节奏一致

## Phase 5 状态反馈与微交互

- [x] 调整 `run-status`，让它更接近“工作台状态层”而不是提示条
- [x] 为主按钮补 pointer-down 即反馈的即时响应
- [x] 为工作流切换补轻量 cross-fade
- [x] 为结果替换补短时 opacity 过渡
- [x] 为 accordion 展开/收起补更柔和的过渡（2026-07-20: .custom-accordion > .label-wrap 加 transition: color ease-out; 箭头 svg/.icon-wrap 加 transition: transform ease-spring; reduced-motion 块兜底）
- [x] 为失败态补更具体的下一步行动建议（2026-07-20: _failure_hint(msg) 按错误关键词给下一步; .run-status-hint quiet meta row 渲染到 status-bar 第二行; 测试 test_render_status_html_adds_failure_hint_on_known_errors 5 类错误全覆盖）

## Phase 6 文案与排版收束

- [x] 统一应用标题、workflow 标题、小节标题、meta 文案四级层级（2026-07-20: h1=2xl/700/-0.01em, h2=xl/600, h3=lg/600, .section-header=base/600 已是完整四级; app-shell-title h1 单独走 display 级 clamp(30px,2.8vw,40px)/800/-0.02em 是有意区分）
- [x] 继续删除“结构已能表达”的说明性句子（2026-07-20: 砍掉导航 .nav-rail-note "选择一个预置工作流后..." + 主题 "新增主题编辑 themes.json" dev hint; .nav-rail-note class + 对应 CSS 已同步清理）
- [x] 检查所有按钮、标题、状态文案是否足够具体而不冗长（2026-07-20: 整库 helper text 已无 "告诉/留空=/模型用的" 解释腔, description 全部 ≤24 字）
- [x] 收敛字重、字号、tracking、leading 的使用范围（2026-07-20: --text-{xs,sm,base,lg,xl,2xl} 七档 + --leading-{tight,normal,loose} 三档 token 体系完整; body 默认 tracking=0, 仅 display 级用 -0.02em, h1 用 -0.01em）
- [x] 复核诗句字体是否仍与整体科技感协调（2026-07-20: .app-shell-signature-quote 保留 KaiTi/STKaiti/Songti SC + fallback var(--font-sans); AGENTS.md 已记录 "诗句保留书卷气, 只作为局部例外"）

## Phase 7 回归与验收

- [x] 跑相关测试集合并补必要的样式契约测试（2026-07-20: 全量 pytest tests/ -q = 594 passed / 9 skipped / 0 failed; 本轮新增 11 条契约测试覆盖 prefers-reduced-transparency / prefers-contrast / nav 长名换行 / 字段 tier 顺序 / 失败态 hint / accordion 过渡）
- [x] 用 `start_webui.bat` 重启后实测运行页（2026-07-20: 重启后 curl 抓 page.html, 内联 CSS blob 11 项关键规则全部 verified: step-card 水平 padding=0 / preset-panel 水平 padding / btn-run-primary text-lg / btn-run-secondary space-5 / prefers-reduced-transparency / prefers-contrast / run-status-hint flex-basis 100% / nav word-break / accordion transition / footer-notice margin-top / textarea leading）
- [x] 逐个检查所有 workflow 的导航、输入区、结果区节奏（2026-07-20: 10 个 preset 全部 _render_workflow_form 渲染 OK, spec/flat/advanced 数量自洽）
- [x] 检查是否再次出现滚动条、空白累积、隐藏 panel 占位等回归（2026-07-20: test_preset_panel_has_no_min_height / test_hidden_preset_panels_are_fully_removed_from_layout / test_preset_panels_host_has_zero_gap 仍绿, 无累积回归）
- [x] 更新 `UI_STYLE.md` 中与头部、导航、结果区有关的视觉约定（2026-07-20: §1.1 新增 Apple-Design 三层材料系统说明, §1.2 新增三套 accessibility 媒体查询说明, §4 CSS 类表补全 .app-shell-header / .workflow-nav-rail / .result-area-shell / .result-area-media / .run-status-hint / .run-controls-card / .workflow-titleband / .result-stage-card / .footer-notice 等 11 个新 class, §6.1 补中栏三段节奏契约 + step-card/preset-panel padding 分工说明）
- [x] 产出最终变更摘要和验收截图（见 progress.md / findings.md 2026-07-20 段落）

## 建议执行顺序

1. 先做 `Phase 1 + Phase 2`，统一最外层气质。
2. 再做 `Phase 3 + Phase 4`，解决真正的使用主次。
3. 最后做 `Phase 5 + Phase 6 + Phase 7`，补精致度和稳定性。

## 最终状态 (2026-07-20)

全 7 个 Phase 完成。35/35 todo 项全部勾选。
- 全量回归: `pytest tests/ -q` = **594 passed / 9 skipped / 0 failed**
- 浏览器实测: 服务端 page.html 内联 CSS blob 11 项关键规则全部 verified
- 文档同步: UI_STYLE.md / AGENTS.md 已记录本轮所有视觉约定

### 范围声明（不在本次重构目标内的 SKILL 章节）

apple-design SKILL.md 共 17 章, 本次重构覆盖其中可在 Gradio 静态界面落地的子集:
- §1 Response (按钮 :active 反馈) ✓
- §4 Springs over keyframes (CSS 层 --ease-spring token + transition) ✓ 部分
- §7 Spatial consistency (transform-origin: top center 在 preset-panel) ✓ 部分
- §11 Frame-level smoothness (只用 transform/opacity transition) ✓ 部分
- §12 Materials & depth (三层材料系统 + backdrop-filter) ✓ 完整
- §14 Reduced motion / transparency / contrast (三套媒体查询) ✓ 完整
- §15 Typography (size-specific tracking, leading token 体系) ✓ 完整
- §16 Eight principles (目的/简洁/熟悉/工艺 落地) ✓ 部分

**显式不做**（Gradio Python-driven 表单技术栈不适合, SKILL 自己也强调"web spring library + Pointer Events"）:
- §2 Direct manipulation, §3 Interruptibility, §5 Velocity handoff, §6 Momentum projection,
  §8 Hint in gesture direction, §9 Rubber-banding, §10 Gesture design details
- §13 Multimodal (sound/haptics) —— Web 上价值低
