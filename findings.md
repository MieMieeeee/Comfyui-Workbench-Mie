# 发现记录

## 2026-07-18

- 当前产品方向已明确：永久放弃 `历史记录`，页面目标转向“创意工作台”。
- 现有问题不是单一配色问题，而是实现、文档、测试、样式四套心智模型并存。
- 代码现状与测试现状已经确认 `历史记录` tab 被移除，但多份文档和部分 E2E 断言仍指向旧结构。
- `tokens.css` 仍保留大段历史页专用样式，属于视觉和维护负担。
- 顶层运行页目前已经具备左右布局基础，但“头部缺位、工作台主次不稳、结果区不够强”仍是主要设计痛点。
- 归档类文档中仍可见 `历史记录` 关键词，主要是 review / audit 历史记录，不再属于当前产品说明。
- 浏览器实检后确认第二轮最值得修的是比例问题，而不是继续堆样式：左导航偏窄、参数区偏挤、结果区偏强、按钮层级偏重。
- 把 `tokens.css` 里的历史页专属块整体删掉后，主样式表明显更干净，后续继续调视觉阻力更小。
- 引入 `apple-design` 视角后，当前页面的主要问题不再是“还不够好看”，而是“材料系统过碎、标题系统重复、头部过像 Banner、结果区还不够像主舞台”。
- 当前最值得做的不是继续修单点，而是一次性统一 `头部 / 导航 / 输入区 / 结果区 / 状态反馈` 五个部分的材料与层级。
- 对当前 Gradio 项目来说，最现实的 `apple-design` 落点不是复杂手势，而是 `克制、稳定材料、结果优先、即时反馈、文案收束`。
- Phase 1 实测后确认：头部的 CSS 已薄化到 `padding 16x20 / min-height 96 / shadow-sm / blur 18`，但实际渲染高度仍约 `145px`，说明 Gradio wrapper 本身还在贡献额外高度，后续可继续压缩。
- 左侧导航的轻量材料层已经落地：实测为 `blur 20 + shadow-sm`，从器物感上已明显弱于旧卡片。
- 工作流头区从卡片改为标题行后，浏览器实测 `background:none / border-bottom / shadow:none` 已生效。
- 结果舞台实测已有更强边界与 `shadow-lg`，开始和中间输入层拉开层级差。
- Phase 2 实测确认：导航搜索框做成轻工具条后，实际为 `rgba(12,14,18,0.62)` 半透明底、`40px` 高度、细边界，已经和内容区普通输入框分层。
- 左侧工作流列表 hover 规则已改为 `transform:none`，选中态实测为 `轻底 + 细高亮条 + 无浮卡阴影`，更接近 source list。
- 系统状态文字实测已降到 `10px / text-faint`，开始从“系统卡片内容”收回到辅助状态层。
- 结果区 `作品预览` 标题和帮助文案已降到 `12px / 10px` 两级，结果舞台本身开始更像主角。
- 仅重启服务不足以证明页面已更新；浏览器标签页可能仍持有旧 DOM/CSS，必须主动刷新后再量 computed style。
- Phase 3 实测后确认：`nav-divider` 已隐藏、`nav-group-system` 已通过 top border 接到同一材料内，导航与系统区开始真正合流。
- `step-card` 实测已变为 `8px 0 12px` 的纵向节奏，不再保留横向包裹感。
- `result-area-shell result-area-default` 已在 `zimage / sca12_motion / sca12_replace / klein_edit / liveportrait` 五组 workflow 中全部出现，说明默认 example 承载面已经统一。
- Phase 4/5 实测确认：`workflow-stage-header-subtitle` 现在是 `10px / muted / max-width` 的 meta 层，不再像第二行卖点。
- `custom-accordion` 去掉 accent 左边框后，浏览器实测为 `border-left 0 / border-top 0.66px`，更接近 quiet disclosure。
- `run-status-bar` 实测为 `rgba(26,29,35,0.72) + blur(12px) + min-height 40px`；running 态规则里已无 pulse / glow，状态层稳定感明显更强。

## 2026-07-19

- 把高级参数下沉到运行控制之后时，`inputs` 的扁平重建时机也必须一起后移；否则 `qwen_image_2512_4step` 这类带 `int_random` 的 advanced 字段会从返回列表里消失，直接把 example / rerun / run_workflow 的 flat 索引打乱。
- 视频类的 `预估段数` 更适合作为运行控制段内部的 meta 提示，而不是独立插在输入参数和主按钮之间；否则中栏会重新长回“四段半”的断裂感。
- 这次再次证明“重启服务”不等于“验证了最新页面”：如果服务是在后续 patch 前启动的，浏览器即使硬刷新也只会忠实显示旧代码对应的页面。必须在最终代码稳定后重新跑一次 `start_webui.bat`。
- 用新的浏览器会话并加 cache-busting URL 后，页面可见文本已直接验证到本轮改动：`zimage` 首屏出现 `② 运行控制`；`sca12_replace` 出现 `① 输入参数 → ② 运行控制 → ③ 高级参数`。
- 轻量 cross-fade 在 Gradio 里最稳妥的落点不是复杂状态机，而是让 `.preset-panel` 和 `.result-area-shell` 在新 DOM 可见时做短时淡入，并同时提供 `prefers-reduced-motion` 关闭入口。
- 文本文字噪音里最显眼的一类不是“说明太长”，而是同一句 `help` 同时出现在输入框 placeholder 和 info 两处；把默认 placeholder 回退为空后，首屏会立刻安静一层，但字段下方的说明并不会消失。
- `workflow-stage-header` 下的 `description` 即使已经满足 30 字约束，仍可能太像完整说明句；把它继续压到约 24 字以内后，工作流标题区更接近 meta copy，而不是第二个说明段落。
- 高频 helper text 的“吵”主要来自解释腔，而不是长度本身：像 `告诉系统…`、`模型用的…`、`留空 = …` 这种写法，即使不长，也会把界面读感拉回教程页。
- `SCAIL2` 这一组最值得优先收，因为它同时占据图片输入、视频输入、提示词和帧数四类字段；只改这 4 个 help，首屏噪音就会立刻降下来。
- `LivePortrait` 的 file 输入帮助在 compact snapshot 里不总是直接展开显示，所以这组更适合用“数据测试 + 页面结构检查”双证据，而不是只依赖 snapshot 文本。
- 结果舞台真正的不一致不在 wrapper 有没有，而在“卡面由谁承载”：之前 image / video / audio 都进了 `result-area-shell`，但边框、背景、圆角还散落在各自标签的 inline style 里，所以音频总像临时塞进去的播放器。
- 把卡面统一收回 `.result-area-media` 之后，媒体元素本身只做内容物；这样 image / video / audio 的结构层级就一致了，后续再调材质时也只需要改一处 CSS。
- 音频结果不适合沿用视频的承载高度；现场量到 `160px` 的 audio stage 比 `220px` 的 image/video stage 更像一个安静的播放器位，而不是空一大片的“伪视频框”。
- 结果区最“教程页”的两句其实不是字段 help，而是默认 caption 和页脚限制说明；把它们收成 `示例结果，运行后自动替换。` 与 `素材上限 · ...` 后，右栏立刻更像作品舞台而不是使用说明。
- `file-fallback` 之前的问题不只是文案“已生成/未知输出格式”太吵，还包括 dashed 边框和块状背景太像告警条；换成 flex meta row + 轻背景后，它更像结果区里的次级动作。
- 长期只跑精选子集（167 / 177 / 244 之类）会系统性掩盖全量回归；只有 `pytest tests/ -q` 才能反映真实红绿。这轮结果区收敛的实际全量是 `12 failed`，之前一直没被发现。
- `sca12_motion / sca12_replace` 的 spec 顺序从 `[image, 362 text, 348 text, 360 text, 469 video, 469 frame, 367, 464]` 改成 `[image, 362 text, 360 text, 469 video, 348 text, 469 frame, 367, 464]` 是有意重排（348 跟着 469 video 走“驱动视频 + 它的抠图提示词”成组）。实际运行不回归，因为 `run_workflow` / 表单渲染 / example 映射 / manifest 回填全链路都按 `user_facing_inputs` 顺序消费；只有测试里硬编码 positional args 的地方会错位。
- 2026-07-17 那轮 layout_polish（commit `0a34fd4`）锁了一批 CSS 契约（step-card 水平 padding / 主按钮字号 `--text-lg` / 两按钮水平 padding 同 token / textarea `line-height` / 页脚 `限制:` 文案）。这轮 apple-design 重构有意改了其中 5 条（`.step-card` 去 padding 是 Phase 3 方向、按钮字号降档、textarea 规则删了、页脚文案改成 `素材上限`），但没同步那批测试，所以全量回归里它们一直红。
- `test_render_form_dup_node_id.py` 之前硬编码 `spec[4]/spec[5]` 是脆弱写法；改成按 `type == "file:video"` 和 `node_id == "469" 且 type == "int"` 动态定位之后，对 spec 顺序重排免疫，跟它下面 `test_render_form_sca12_replace_one_component_per_spec` 的写法也对齐了。

## 2026-07-20 — apple-design 全界面重构收口发现

- "完成整个重构" 必须先拆成可验证的交付物清单 (全量测试绿 / todo 全勾 / SKILL §14 媒体查询齐 / UI_STYLE.md 同步 / 浏览器实测), 不能靠"主观感觉差不多了"收尾。
- B 类 layout_polish 旧契约和 apple-design 新契约的本质冲突在 `.step-card` 水平 padding: layout_polish 要 step-card 自己有水平 padding (字段不贴卡片边), Phase 3 要 step-card 水平 padding=0 (连续工作台面去包裹感)。两个测试锁相反方向。真正的解法不是二选一, 而是把"字段呼吸"的职责上移到父 `.preset-panel` —— step-card 之间连续 (Phase 3 ✓), 字段最终不贴容器边 (layout_polish ✓)。这种"职责转移"比"改一个测试承认另一个"更对。
- `prefers-reduced-transparency` 和 `prefers-contrast` 是 apple-design SKILL §14 明确要求但容易被忽略的两套媒体查询。prefers-reduced-motion 大家都记得 (动效降级), 但磨砂面在用户偏好"不要透明"或"更高对比"时必须能 fallback 到实色 + 明确边界, 否则 legibility 会塌。
- 长 workflow 名 (如"语音合成 (Qwen3-TTS VoiceDesign)" 28 字) 在窄导航里用 `white-space:nowrap + ellipsis` 会被截掉一半, 用户认不出。改成 `word-break:break-word + line-height:leading-tight` 后允许两行, 长名完整可读。CJK + ASCII 混合名必须显式 break-word, 否则浏览器只在 CJK 之间断。
- "全部 spec 显式 tier" 是 Phase 3 中栏三段节奏 (① 输入参数 → ② 运行控制 → ③ 高级参数) 的前提。如果 spec 没有 tier, _render_workflow_form 无法稳定地把字段分到 basic 段还是 advanced 段; 如果 advanced 字段插在 basic 中间, 节奏退回成"分组卡片表单"。这是数据层 (params.json) 而不是代码层的契约, 锁在 test_field_tier_always_explicit + test_field_order_basic_before_advanced。
- 失败态给"下一步建议"而不是只报错, 对应 AGENTS.md 的 Failure-investigation priority (用户输入 → ComfyUI 进程 → 资源 → 工作流)。按错误关键词 (upload/queue/timeout/patch/cuda/file-size) 推断最可能的下一步, 用户不用看完错误信息就知道该检查什么。这是 SKILL §16 "agency / wayfinding" 的具体落地: "Where can I go? How do I get out?"
- Gradio 6 的 launch(css=...) 注入路径不在 `/theme.css` 端点 (那是 Gradio 自带 theme 样式), 也不在 `./assets/index-*.css` (那是 SPA 入口), 而是嵌在 page.html 的内联 `<script>` 块里作为 JSON config 的一部分。CSS 字符串里的 `>` 会被转义成 `\u003e`, `\n` 会被转义成 `\\n`。验证服务端 CSS 是否最新, 必须抓 page.html 然后解码内联 script, 而不是抓 theme.css。
- "重启服务" 不等于 "页面已更新": 旧 python 进程可能还在持有端口 (本机这次有 PID 50244 / 69344 / 24544 三个先后持有 8199 的进程)。必须 `netstat -ano | grep 8199` 找到当前 LISTENING 的 PID, `taskkill /F` 杀掉, 再启新的, 否则浏览器拿到的还是旧 CSS。
- apple-design SKILL 17 章里, §2/§3/§5/§6/§8/§9/§10 (手势/中断/动量/橡胶带) 全部依赖 Pointer Events + JS spring library。Gradio 是 Python-driven 表单, 没有挂载自定义手势的合理入口。继续投入这些章节 ROI 极低, 应该在计划里显式标记为"非目标", 否则会一直觉得"还差很多"——其实差的是 Gradio 不该做的事。


