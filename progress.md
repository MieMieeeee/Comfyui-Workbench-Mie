# 进度日志

## 2026-07-18

- 已完成设计澄清：确认永久移除 `历史记录`，确认目标风格为“创意工作台”。
- 已产出高层设计方向：头部、导航、参数区、结果区的新版信息架构。
- 已建立规划文件与设计文档，进入执行阶段。
- 已按 TDD 先补 4 个新工作台测试，确认它们先失败后再实现。
- 已完成运行页结构升级：应用头部、副标题、工作台骨架类名、四段式参数区、作品预览标题。
- 已更新 `UI_STYLE.md` 与 `ADDING_WORKFLOWS.md`，移除主叙事中的历史记录入口说明。
- 已跑相关测试集合，结果 `164 passed`。
- 已追加第二轮视觉回归测试，锁定头部 pills、导航说明、预览动作工具条和历史页死样式清理。
- 已完成第二轮视觉打磨：导航加宽、左/右工作区比例改为 `5 / 6`、按钮尺寸收紧、结果区媒体高度受控。
- 已用浏览器实际检查当前页面，把“导航过窄、结果区过强、按钮过大”的问题收口到实现里。
- 已再次跑相关测试集合，结果 `169 passed`。
- 已安装 `apple-design` skill，并据此重新审查整套 Gradio 工作台。
- 已把审查范围从头部扩展到 `头部 / 左侧导航 / 中间输入区 / 右侧结果区 / 状态反馈` 五部分。
- 已产出 `docs/plans/2026-07-18-apple-design-full-ui-redesign.md` 全界面重构稿。
- 已产出 `docs/plans/2026-07-18-apple-design-full-ui-todo.md` 独立执行清单，供后续按阶段落地。
- 已进入实现阶段的 Phase 1，并按 TDD 先补了头部、导航、工作流标题行、结果舞台的 4 条新样式契约。
- 已完成 Phase 1 第一轮实现：头部薄化、导航去重卡片化、工作流头区缩成紧凑标题行、结果舞台升格。
- 已运行 `pytest tests/test_css_theming.py tests/test_ui_workbench_redesign.py tests/test_e2e_render.py -q`，结果 `184 passed`。
- 已用 `start_webui.bat` 重启 WebUI，并在浏览器确认新的材料层级已真实生效。
- 已完成 Phase 2 第一轮实现：导航搜索框轻工具条化、系统状态 meta 化、工作流列表 source-list 化、结果区标题与帮助文案降权。
- 已按 TDD 新增 Phase 2 契约测试，并运行 `pytest tests/test_css_theming.py tests/test_ui_workbench_redesign.py tests/test_e2e_render.py -q`，结果 `189 passed`。
- 已再次重启 WebUI，并在浏览器通过 computed style 验证搜索框、选中态、结果区 meta 文案均已真实生效。
- 已完成 Phase 3 第一轮实现：导航/系统区材料合流、step-card 去横向包裹感、结果区 wrapper 统一。
- 已新增 `test_ui_helpers.py` 与样式契约测试，运行 `pytest tests/test_css_theming.py tests/test_ui_helpers.py tests/test_ui_workbench_redesign.py tests/test_preset_must_have_example.py tests/test_e2e_render.py -q`，结果 `244 passed`。
- 已重启 WebUI 并刷新页面，在浏览器实测 `zimage / sca12_motion / sca12_replace / klein_edit / liveportrait` 五组 workflow 均吃到统一的 `result-area-shell result-area-default` 承载面。
- 已完成下一轮中间区/状态层打磨：subtitle meta 化、accordion quiet disclosure 化、run-status 状态层化。
- 已按 TDD 新增相关样式契约，并运行 `pytest tests/test_css_theming.py tests/test_run_status_progress_capsule.py tests/test_ui_workbench_redesign.py -q`，结果 `122 passed`。
- 已重启 WebUI 并在浏览器 computed style 中确认上述三项样式真实生效。

## 2026-07-19

- 已按 TDD 先补三段流与微交互相关失败测试：锁定 `② 运行控制`、`③ 高级参数`、`run-controls-card` 节奏、主按钮按压反馈、workflow 切换淡入、结果替换淡入、`prefers-reduced-motion` 降级。
- 已把中栏结构从 `输入参数 → 高级参数 → 段数提示 → 运行控制` 改为 `输入参数 → 运行控制 → 高级参数`，并把视频类 `预估段数` 收进运行控制段内部。
- 已把高级折叠标题从 `🔧 高级参数(一般不用改)` 收束为 `③ 高级参数`，让中栏更像连续三段流而不是解释性表单。
- 已补 `run-controls-card` 的独立节奏，并为 `.btn-run-primary:active`、`.preset-panel`、`.result-area-shell` 增加更轻的按压与淡入反馈。
- 已新增 `@media (prefers-reduced-motion: reduce)`，关闭本轮新增的淡入/按压过渡，避免动效和可访问性相互冲突。
- 已运行 `pytest tests/test_ui_workbench_redesign.py tests/test_css_theming.py -q`，结果 `122 passed`。
- 已继续运行 `pytest tests/test_ui_helpers.py tests/test_e2e_render.py tests/test_preset_must_have_example.py tests/test_run_status_progress_capsule.py -q`，结果 `139 passed`。
- 已重启 `start_webui.bat`，并在全新浏览器会话中核对：`zimage` 可见 `② 运行控制`，`sca12_replace` 可见 `① 输入参数 → ② 运行控制 → ③ 高级参数`，右侧结果舞台与留白未回退。
- 已继续按 TDD 收敛文案噪音：新增 `description <= 24` 与“文本输入不再把 help 同句重复塞进 placeholder”两条失败测试后再实现。
- 已把 6 个仍偏长的 preset 描述压到更像 meta copy 的长度，并把文本类控件的默认 placeholder 改为“仅显式声明才显示”，不再自动复写 `help`。
- 已运行 `pytest tests/test_display_name_normalization.py tests/test_ui_workbench_redesign.py -q`，结果 `27 passed`。
- 已继续运行 `pytest tests/test_preset_must_have_example.py tests/test_e2e_render.py tests/test_css_theming.py -q`，结果 `199 passed`。
- 已再次重启 `start_webui.bat` 并在新浏览器会话中确认：`zimage` 标题下描述已缩成 `Z-Image 文生图，多尺寸输出。`；`sca12_replace` 的抠图提示词文本框不再显示与 info 重复的 placeholder。
- 已继续按 TDD 收敛高频 helper text：新增 `SCAIL2 / LivePortrait / 音频` 三组 copy 契约测试后，再统一修改 `params.json` 中对应 help 文案。
- 已把 `sca12_motion / sca12_replace` 的抠图提示词、正向提示词、最高帧数文案改成更短的任务指令；已把 `liveportrait` 的参考脸图/驱动视频说明改成更像任务流。
- 已把 `qwen3_tts / ace_step_15_music` 的首屏与高频高级参数说明压短，去掉 `告诉系统 / 模型用的 / 留空 =` 这类解释腔。
- 已运行 `pytest tests/test_display_name_normalization.py -q`，结果 `12 passed`。
- 已继续运行 `pytest tests/test_ui_workbench_redesign.py tests/test_preset_must_have_example.py tests/test_e2e_render.py -q`，结果 `112 passed`。
- 已再次重启 `start_webui.bat` 并在新浏览器会话中确认：`sca12_replace` 首屏已显示更短的 `参考图主体 / 驱动视频主体 / 0 = 全部加载`；`qwen3_tts` 与 `ace_step_15_music` 首屏 helper 也已明显收短。
- 已按 TDD 推进结果舞台一致性：先补失败测试，锁定 image / video / audio 都要带 `result-area-kind-*`，未知输出 fallback 也不能跳出 `result-area-shell`，媒体卡面由 `.result-area-media` 统一承载。
- 已把 `_media_to_html` 与默认 example 输出改成统一的 `result-area-kind-image|video|audio` + `result-area-asset` 结构，并把图片网格项抽成 `result-area-grid-item`，去掉原来零散的 inline 卡面样式。
- 已把结果舞台的表面语义收回到 CSS：`.result-area-media` 现在统一提供 padding / background / border / radius / shadow；音频舞台单独收成更紧凑的 `160px` 高度。
- 已顺手修正一个旧测试误杀：`test_new_preset_output_box_renders_gradio_api_route` 不再把 `src` 引号风格写死成单引号。
- 已运行 `pytest tests/test_ui_helpers.py tests/test_new_presets_from_comfyui_skill.py tests/test_css_theming.py -q`，结果 `217 passed`。
- 已继续运行 `pytest tests/test_preset_must_have_example.py tests/test_e2e_render.py tests/test_display_name_normalization.py -q`，结果 `106 passed`。
- 已再次重启 `start_webui.bat` 并在新浏览器会话中量到：`zimage` 的结果舞台为 `result-area-kind-image` / `220px`；`sca12_replace` 为 `result-area-kind-video` / `220px`；`qwen3_tts` 与 `ace_step_15_music` 为 `result-area-kind-audio` / `160px`。
- 已继续按 TDD 收敛结果区 meta copy：新增失败测试，锁定默认说明文案、页脚素材上限文案，以及未知/降级 fallback 的动作条表达。
- 已把结果区默认说明从“默认展示示例效果；开始运行后...”收成 `示例结果，运行后自动替换。`，并把页脚从 `限制:` 收成 `素材上限 · ...`。
- 已把 `file-fallback` 从“已生成 / 未知输出格式”提示句改成更安静的结果动作条：统一显示 `下载原文件`，并用 `file-fallback-label` / `file-fallback-extra` 承载标签和附加内容。
- 已把 `file-fallback` 样式改成 quiet meta row：`display:flex`、细实线边框、极浅背景、8px gap，不再像 dashed warning banner。
- 已运行 `pytest tests/test_ui_workbench_redesign.py tests/test_ui_helpers.py tests/test_css_theming.py -q`，结果 `167 passed`。
- 已继续运行 `pytest tests/test_preset_must_have_example.py tests/test_e2e_render.py tests/test_new_presets_from_comfyui_skill.py tests/test_display_name_normalization.py -q`，结果 `177 passed`。
- 已再次重启 `start_webui.bat` 并在新浏览器会话中确认：默认结果区文案已变为 `示例结果，运行后自动替换。` 与 `素材上限 · ...`；同时在当前页面 CSS 环境中量到 `.file-fallback` 为 `display:flex / align-items:center / bg rgba(255,255,255,0.02)`。

### 全量回归收敛 (2026-07-19 续)

- 已发现之前几轮只跑了精选子集（167 / 177 之类），全量 `pytest tests/ -q` 实际是 `12 failed`，被掩盖了一段时间。
- 已定位 12 个失败的根因分两类，都是这次重构“有意改契约、但旧测试没同步”:
  - **A 类（7 个）— params.json spec 顺序回归**: `sca12_motion` / `sca12_replace` 的 `348 text`(驱动视频抠图提示词) 从 `469 video` 之前挪到之后，所有硬编码 positional args 的测试错位。经确认这是有意的新顺序，且 `run_workflow` 全链路按 `user_facing_inputs` 顺序消费，实际运行不回归。
  - **B 类（5 个）— layout_polish 2026-07-17 锁定的 CSS 旧契约被这轮重构吃掉**:
    - `test_step_card_has_top_and_horizontal_padding` — `.step-card` 水平 padding 改回 `0` (Phase 3 去横向包裹感)
    - `test_btn_run_primary_font_size_is_text_lg` — 主按钮字号 `--text-lg` 降到 `--text-base`
    - `test_run_buttons_share_horizontal_padding_token` — 两按钮水平 padding 分叉 (`space-5` vs `space-4`)
    - `test_textarea_has_explicit_line_height` — textarea 的 `line-height: var(--leading-*)` 被删
    - `test_footer_limit_notice_has_breathing_room` — 页脚文案 `限制:` 改成 `素材上限 · ...`（这一项文字层面已经是本轮想要的，但测试还按旧文案断言）
- 已按用户决定“保留新顺序（348 在后）”修了 A 类全部 7 个:
  - `tests/test_also_patch.py` 的 `_run_with` positional_args + 注释
  - `tests/test_render_form_dup_node_id.py` 改成按 type/node_id 动态定位（不再硬编码 spec[4]/spec[5]）
  - `tests/test_fixed_patches_and_example.py::test_run_workflow_applies_fixed_patches` 的 positional args
  - `tests/test_run_workflow_preset.py::_replace_values` 的 8 个值顺序 + 注释
- 已跑 `pytest tests/test_also_patch.py tests/test_fixed_patches_and_example.py tests/test_render_form_dup_node_id.py tests/test_run_workflow_preset.py -q` -> `23 passed`。
- 已跑全量 `pytest tests/ -q` -> **`5 failed, 581 passed, 9 skipped`**，从 12 降到 5。
- 剩余 5 个全是 B 类 layout_polish 旧契约，按用户指示“继续沿结果区往下收，不扩散到别的模块”，本轮先不动；待结果区轮次结束后再统一处置（恢复契约 or 更新测试承认新值，需用户拍板）。

## 2026-07-20 — apple-design 全界面重构全部落地

### 用户目标

"完成整个重构" —— 把 apple-design SKILL 重构从部分推进到全部完成。

### 完成判据 (按 SKILL § + apple-design todo 7 Phase)

1. 全量 `pytest tests/ -q` 必须全绿
2. apple-design todo 7 个 Phase 全部勾完
3. SKILL §14 补齐 `prefers-reduced-transparency` / `prefers-contrast` 两套媒体查询
4. `UI_STYLE.md` 同步本轮所有视觉约定
5. 浏览器实测验证（restart + computed style）

### 实际交付 (全部 5 项达成)

**1. 全量回归全绿**: `pytest tests/ -q` = **594 passed / 9 skipped / 0 failed** (从本轮起点 12 failed 收口)

**2. apple-design todo 35/35 全勾**: 见 `docs/plans/2026-07-18-apple-design-full-ui-todo.md`

**3. SKILL §14 三套媒体查询完整**: `prefers-reduced-motion` (原有) + `prefers-reduced-transparency` (新) + `prefers-contrast` (新)

**4. UI_STYLE.md 同步**: §1.1 三层材料系统 / §1.2 三套媒体查询 / §4 补 11 个新 class / §6.1 三段节奏契约

**5. 浏览器实测**: 重启 WebUI 后抓 page.html, 内联 CSS blob 11 项关键规则全部 verified

### 本轮具体改动 (按 Phase)

| Phase | 改动 | 新增测试 |
| --- | --- | --- |
| B 类回归收口 | step-card 水平 padding=0 (Phase 3 契约) + 字段呼吸转交父 .preset-panel; btn-run-primary 字号恢复 --text-lg; 两按钮水平 padding 统一 --space-5; textarea line-height; 页脚文案断言更新 | 修 test_layout_polish_* 5 个; 修 test_step_card_has_top_and_horizontal_padding 改查父 panel |
| SKILL §14 | 新增 @media (prefers-reduced-transparency) + @media (prefers-contrast) 两块, 覆盖三层磨砂面 | test_prefers_reduced_transparency_disables_backdrop_filter / test_prefers_contrast_more_adds_explicit_borders |
| Phase 1/2 | nav label white-space:nowrap → word-break:break-word (28 字长名不再截断) | test_custom_radio_label_allows_wrapping_for_long_workflow_names |
| Phase 3 | 全部 spec 显式 tier; ltx_23_t2v_distill / qwen_image_2512_4step advanced 错位修正; 最后一个解释腔 helper 删除 | test_field_order_basic_before_advanced / test_field_tier_always_explicit |
| Phase 5 | accordion label transition + 箭头 spring; _failure_hint(msg) 5 类错误下一步建议; .run-status-hint quiet meta row | test_render_status_html_adds_failure_hint_on_known_errors (5 case) + test_failure_hint_css_uses_quiet_meta_styling + test_custom_accordion_has_smooth_transition |
| Phase 6 | 砍 nav-rail-note 结构性解释句 + class + CSS; 砍主题 tab dev hint; 四级标题层级 + token 体系审计完成; 诗句字体保留 (AGENTS.md 已记录) | 修 test_build_ui_has_visual_polish_classes_for_header_nav (移除 nav-rail-note 期望) |
| Phase 7 | UI_STYLE.md §1.1/§1.2/§4/§6.1 同步; 10 preset 全部渲染 OK; 浏览器实测 11/11 verified | (验收, 无新测试) |

### 显式不做的 SKILL 章节

§2/§3/§5/§6/§8/§9/§10 (手势/中断/动量/橡胶带) 依赖 Pointer Events + JS spring library, Gradio Python-driven 表单不适合。§13 (sound/haptics) Web 上价值低。详见 todo 文档末尾"范围声明"。


