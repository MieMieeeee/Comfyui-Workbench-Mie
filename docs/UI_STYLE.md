# UI_STYLE.md — Gradio 界面样式约定

> 这份文档给作者本人和 AI agent 看。`AGENTS.md` 写了"信任模型 + 数据驱动添加工作流"；
> 本文写"长成什么样 + 为什么长这样"。改 UI 前先读完。

## 1. 设计取向

WebUI 是一个**工作流运行器**，不是产品官网。每次发版都会有新 preset 进来，所以 UI
必须对"工作流数量持续增长"友好。具体表现：

- 左侧用 Radio + 搜索框列出所有 workflow，按 `order` 升序、按 `category` 加 emoji 前缀。
- 每个 preset 的表单**预渲染到独立 `gr.Group`**，切 preset 时切 `visible` 不销毁组件，
  这样表单状态保留、上次填的 prompt / 上传的文件不会丢。
- 文件 / 视频输入紧跟预览（thumbnail / video），点击"🚀 开始运行"前先看到结果长什么样。
- 输出区在表单正下方："📜 运行日志"（多行折叠）+ 结果预览 + "🔁 用相同参数再来"
  + "📂 打开 ComfyUI 输出目录"。

SaaS / 着陆页式的装饰（hero 卡 / gradient / SVG illustration）一律不要。Gradio 默认
主题即可，最多在 `launch()` 里传自定义 css 覆盖几个 badge / banner。

## 2. Emoji 图标规范

为了让"加新 preset / 加新按钮"时有现成词汇可挑，不至于每次自由发挥。约定如下：

### 2.1 分类前缀（左侧 Radio label）

`_CATEGORY_ICON` 字典，`_category_icon()` 取：

| category | icon | codepoint | 含义 |
| --- | --- | --- | --- |
| `video` | 🎬 | U+1F3AC | 文生视频 / 视频编辑类 |
| `image` | 🖼️ | U+1F5BC + VS-16 | 文生图 / 图像编辑 |
| `audio` | 🔊 | U+1F50A | TTS / 音频类 |
| `3d` | 🧊 | U+1F9CA | 3D 生成类 |
| `other` (默认) | 📦 | U+1F4E6 | 兜底 |

新增 category 时**先**在 `_CATEGORY_ICON` 里加 mapping，再用——别在 `params.json`
里写一个 `_CATEGORY_ICON` 没收录的 category 然后期待前端自己想办法。

### 2.2 组件 / 按钮前缀

| 出现位置 | emoji | 说明 |
| --- | --- | --- |
| 文件上传（image / video） | 🖼 / 🎞 | 文件输入旁的预览组件用 `gr.Image` / `gr.Video`，show_label=False |
| 参数调节（slider / int / float） | 🎚 | 默认放在主区域，basic tier |
| 高级参数折叠 | 🔧 | `gr.Accordion("🔧 高级参数(一般不用改)", open=False)` |
| 加载示例素材 | 📥 | `gr.Button("📥 加载示例素材", ...)` |
| 随机提示词 | 🎲 | `gr.Button("🎲 随机提示词", ...)` 和 `🎲 随机3条` |
| 开始运行 | 🚀 | `gr.Button("🚀 开始运行", variant="primary", size="lg", scale=3)` |
| 用相同参数再来 | 🔁 | 跑成功后出现的次按钮，`.btn-run-secondary` 降级样式，hidden 在 success 前 |
| 输出区（图片 / 视频） | 🖼 / 🗂 | gallery / video 嵌入输出区 |
| 完整健康检查 | 🔍 | `gr.Button("🔍 完整健康检查", ...)` |
| 系统设置 tab 标题 | ⚙️ | `gr.Markdown("## ⚙️ 系统设置")` |
| 加载上次成功参数 | 📂 | `gr.Button("📂 加载上次成功参数", ...)` |
| 打开 ComfyUI 输出目录 | 📂 | `gr.Button("📂 打开 ComfyUI 输出目录", ...)` |
| 运行日志折叠 | 📜 | `gr.Accordion("📜 运行日志", open=False)` |
| 状态指示点 | 🟢 / 🔴 | ComfyUI 连通：`✅ connected` / `❌ unreachable`，前缀 emoji 随 status |

### 2.3 状态前缀（运行日志 + 顶部 status bar）

运行函数 yield 的 `status_msg` 字符串以 emoji 开头，前端据此切颜色 / 切后续行为：

| 前缀 | 触发行为 |
| --- | --- |
| `✅` | 成功 → `_save_last_run` 落盘 → 显示 "🔁 用相同参数再来" |
| `❌` | 失败 → 显示 `.error-banner` 红条，re-run 隐藏 |
| `⏰` | 超时 → 同 `❌` 路径，红条 + 提示用户去"🔍 完整健康检查" |
| `⏳` | 进行中 → 折叠 "📜 运行日志" 自动展开，progress bar 更新 |

`_run_and_format` 通过 `status_msg.startswith(...)` 判定。**新增状态前缀时同步在
该函数里加分支**（不要直接在外层 `if` 里加 `or` 链——switch 表更可读）。

## 3. 状态持久化约定

### 3.1 上次成功参数

- 路径：`app/data/last_run/{preset_name}.json`
- 写入时机：`_run_and_format` 收到 `✅` 时调用 `_save_last_run`
- 写入内容：`gr` input 组件的当前值列表，JSON-safe 序列化（`None` / `str` / `int` /
  `float` / `bool` 原样，`list` / `tuple` / `dict` 走 `json.dumps`，其它对象 `str(v)`）
- 读取时机：UI 启动时 `_render_workflow_form` 检查 `has_last_run`，按钮 `visible` 切换
- 失败 / 超时**不写**——失败参数回填会让用户反复在同一个错误上转圈

### 3.2 运行 manifest（不要混）

`app/data/runs/{run_id}.json` 是**每一次** run 的完整 manifest（输入 / 输出 / 时间 /
patch / cache_hit），由 `app/history.py` 写入。这是历史记录 tab 的数据源，跟
`last_run` 是两条独立链路。

`last_run` = "上次成功"的极简快照，给 UI 状态恢复用；
`runs/{run_id}.json` = 完整审计，给历史记录 tab + 排查用。
**不要**把它们合并——会破坏 `last_run` 失败不写 的语义。

## 4. CSS 自定义类

自定义 class 在 `app/static/tokens.css` 里定义（`launch(css=_build_launch_css())` 注入），

| class | 用在哪 | 视觉 |
| --- | --- | --- |
| `.btn-run-primary` | 🚀 开始运行（唯一绝对主操作） | 主题色渐变 + glow |
| `.btn-run-primary.is-running` | 运行中态 | 脉冲 + spinner |
| `.run-status-bar` + `.run-status-idle/running/success/failure/timeout` | 顶部运行状态条 (review P2) | 5 态切换颜色 + 图标; running 时带脉冲动画 + icon 旋转 + mm:ss 已耗时 |
| `.sizes-cards` | 「尺寸选项」多选卡片 (review P1) | 替代 gr.CheckboxGroup 默认的「圆点小列表」, 每项独立卡片 + hover + 主题色选中 |
| `.nav-group` / `.nav-group-system` | 左栏导航 / 系统两个 Group (review P3) | 视觉分组 + 小标题 uppercase 灰字 |
| `.nav-divider` | 导航/系统之间的视觉分隔线 | 1px 透明→border→透明的 linear-gradient |
| `.section-header` | 表单内小节标题 (review P4) | 14px primary text + 1px border-bottom, 替代 card-core 嵌套 |
| `.step-card` | 基本输入 Group 容器 (review P4 改后无边框) | 只保留 padding/margin + section-header, 不再加 card-core |

| `.btn-run-secondary` | 🔁 用相同参数再来（次操作，视觉降级） | 低彩度深灰底 + 微弱边框（Light Mode 白底灰边） |
| `.btn-secondary-override` | 📥 / 📂 / 🔍 等次按钮兜底 | 次级灰底 |
| `.card-core` | 主表单 Group / 卡片容器 | 卡片分层底 + 圆角 + 阴影 |
| `.custom-accordion` | 🔧 高级参数 / 📜 运行日志 Accordion | 透明底 + 主题色左 border |
  | `.custom-dataframe` | 历史记录 Dataframe | 表格分层 + hover |
| `.status-badge` + `.status-badge-success/failure/timeout/running/unknown` | 历史记录 Dataframe 状态列 | 圆角胶囊 + 语义色 (绿/红/黄/蓝/灰) |
| `.history-filter-bar` / `.history-filter-preset` / `.history-filter-status` (`.custom-pills`) / `.history-count` | 历史记录筛选条 | 单行 filter row: Preset dropdown + 状态 pills + 计数 + 刷新 |
| `.history-detail-col` | 历史记录右侧详情列容器 | 卡片底 + 圆角,跟左列表视觉对齐 |
| `.detail-card` / `.detail-header` / `.detail-fields` / `.detail-field` (display:contents) / `.detail-label` / `.detail-value` / `.detail-error` | 右侧详情卡片 | 结构化 key-value 网格 + 错误高亮 |
| `.detail-empty` | "无数据"占位 | 居中 + 灰底 |
| `.detail-prompt` / `.detail-prompt-body` | 详情卡片底部提示词摘要 | 上分割线 + 12em 内滚动 |
| `.custom-radio` | 左侧工作流导航 Radio | 卡片化选项 |
| `.error-banner` | 红条，跑失败 / 超时时显示 | 红底 + 黑字 |
| `.error-banner-inner` | `.error-banner` 内部 `gr.HTML` | 让 `gr.HTML` 占满 banner 容器 |
| `.file-fallback` | `_media_to_html` 未知文件类型 / 未知 URL | 灰底 + 下载链接 |
| `.result-area` | 输出区 (视频 / 图片 / 文本容器) | 最小高度占位 |
| `.file-dropzone` | gr.File 拖拽区 | 克制虚线 + 激活态主题色 |
| `.progress-track` / `.progress-bar` / `.progress-text` | gr.Progress 进度条 | 槽隐于背景 + 主题色双段渐变 |
| `.annotation-block` | Recipe / 警告 / 提示统一视觉 | 左 border + radius-sm + 卡片底 |

**视觉焦点唯一性约定**：整个工作台只有 🚀 开始运行 一个绝对视觉焦点
（`.btn-run-primary` 带主题色渐变 + glow）。🔁 用相同参数再来 是次操作，必须用
`.btn-run-secondary`（刻意不消费 `--theme-accent-*`，低彩度不抢镜头）。

新增自定义样式前先想：**Gradio 默认主题能不能直接表达**。能就不加 class；不能再在
`tokens.css` 写规则，并在本文档登记 class。

## 5. 输出媒体渲染

`_media_to_html(media, is_image)` 把 run 函数 yield 的 media 转 HTML 字符串：

| 情况 | 渲染 |
| --- | --- |
| `is_image=True` 且 `media` 是非空 list | `<img>` 网格（`max-width:32%`） |
| `is_image=True` 且 `media` 是单个 URL / 路径 | 单 `<img>` |
| `is_image=False` 且 URL 命中 `.mp4/.mov/.webm/.gif` | `<video controls autoplay>` |
| `is_image=False` 且 URL 命中 `.png/.jpg/.jpeg/.webp` | `<img>`（防止"应该是图片但被当视频"） |
| 未知 HTTP URL | `.file-fallback` banner，显示前 80 字符 |
| 已知本地文件（仓库内） | `/file=` 路由 + `<video>` / `<img>` / 下载链接 |
| 已知本地文件（仓库外） | `.file-fallback` banner + 原始路径 |
| 兜底 | `.file-fallback` banner + 前 80 字符 |

`gr.Video` 不能直接播外部 HTTP URL，所以 HTTP 路径**不**走 `gr.Video`、直接用
`<video>` 标签。Gradio 6 不再支持 `gr.Video(value=url)` 外部源——本约定与该限制
对齐。

### 5.1 `image_sizes` 预设的「用途标签化」（第四阶段 §B）

`params.json` 里 `image_sizes` 类型的 `presets` 数组支持两种条目形式：

| 形式 | 示例 | 用途 |
| --- | --- | --- |
| 纯字符串（向后兼容） | `"1024x1024"` | 老预设 / 极简场景 |
| `{label, value}` 字典 | `{"label": "🎬 1280×720 ｜ 16:9 (横版封面)", "value": "1280x720"}` | 带比例 + 用途说明，降低用户扫描成本（**推荐**） |

`_build_input_component` 把两种形式归一成 Gradio 的 `(label, value)` 元组。**关键
不变式**：`parse_sizes` 只吃 `value`，`label` 不进解析路径 —— `value` 必须是
`parse_sizes` 能严格 fullmatch 的纯净 `WxH`（`1024x1024`，不能是 `1024×1024` 全角或
带文案）。`default` 数组里的值也必须是 `value`，不能是 `label`。

## 6. Tab 与布局

| Tab | 内容 |
| --- | --- |
| `运行` | 左侧 Radio + 搜索 + ComfyUI 状态指示；右侧 `gr.Group` 切换 preset 表单 |
| `历史记录` | Dataframe + Preset 过滤 + 状态过滤 + 详情面板（输入 / 输出 / 耗时 / cache） |
| `系统设置` | ComfyUI 地址 + 🔍 完整健康检查 + GPU/VRAM/模型/自定义节点报告 |

`运行` tab 默认选中。第一次切 preset 不请求网络（除 `🔍 完整健康检查` 外）。

### 6.1 运行表单的两栏工作台布局（第四阶段 + 第六阶段 review 调整）

每个 preset 的 `_render_workflow_form` 用 `with gr.Row(equal_height=False):` 包两栏，
从「长表单页面」变成「左右结构的两栏 AI 创作工作台」：

| 栏 | `gr.Column` | 放什么 |
| --- | --- | --- |
| **左控制栏** | `scale=4` (min_width=380) | 顶部 **运行状态条**（review P2，跨 idle/running/success/failure/timeout 五态）→ ① 输入素材（basic 上传 / 提示词 / 尺寸，section-header 风格，不嵌套 card-core）→ 🔧 高级参数 Accordion → 段数预估（仅视频）→ 📥 加载示例 / 📂 加载上次 → 🚀 **开始运行**（唯一主按钮） |
| **右作品预览栏** | `scale=7` (min_width=460) | 📜 运行日志 Accordion（默认收起）→ 错误红条 → 生成结果区 → 🔁 用相同参数再来（次按钮，降级）→ 📂 打开输出目录 |

第六阶段 review 调整: 左 scale 从 5 改 4, 右 scale 从 6 改 7, 给预览图更大空间。
在 1280px 视口下预览列从 ~430px 涨到 ~687px (1.6x); 1920px 下从 ~800px 涨到 ~1095px,
主图成为真正主角 → review P0 主任务通路。

`build_ui` 顶层的左侧导航 (scale=0 + min_width=200) 跟表单内的左右栏是两套不同 Row, 
互不影响 —— 导航固定 200px, 表单内 4:7 在剩余空间分。

### 6.2 左侧导航的「导航 / 系统」分组（第六阶段 review P3）

build_ui 左侧导航拆成两个 Group + 中间 divider:

| Group | 放什么 |
| --- | --- |
| `.nav-group` (导航) | 🔍 搜索 + 工作流 Radio |
| `.nav-divider` | 1px 透明→border→透明 分隔线 |
| `.nav-group.nav-group-system` (系统) | ComfyUI 连通状态 + 🔄 刷新按钮 |

**theme-injector 仍是 `build_ui()` 顶部的全局唯一 `gr.HTML`**，不在本布局内 —— 它要跨
所有 preset 共用，放进任何一栏都会被 preset 切换的 visibility 影响。两栏只重组
`_render_workflow_form` 内部的表单组件，不碰主题注入器。

**组件创建顺序**（事件绑定靠对象引用，与布局无关，但顺序影响组件 id 区间，测试据此
断言「某组件在哪一栏」）：左栏全部组件 → 右栏全部组件 → 事件绑定。

## 7. 改 UI 时的检查清单

- [ ] 新增按钮 → 在本文档 §2.2 登记 emoji，不挑跟现有按钮重复的
- [ ] 新增 status 前缀 → 同步 `_run_and_format` 的 `startswith` 分支 + §2.3 登记
- [ ] 新增 CSS class → 在 `build_ui()` 里 `css.append(...)` + 在本文档 §4 登记
- [ ] 改了 `_media_to_html` → 加单测覆盖新增分支（list / 单 URL / 未知 / 本地）
- [ ] 改了 `_render_workflow_form` 的输出组件 → 跑 `tests/test_e2e_render.py` 全绿
- [ ] 改了 `_build_history_tab` → 跑 `tests/test_e2e_render.py::test_build_ui_pre_renders_all_panels` 确认 Group 还在
- [ ] 改了 `build_ui()` → 启 `python app/scail2_app.py` 手动过一次，跑成功 / 失败两条路径

## 8. 与 AGENTS.md / ADDING_WORKFLOWS.md 的关系

- `AGENTS.md` §"Defense layers" 列了 UI 这一层的代码模块（`_render_workflow_form`、
  `_media_to_html`、`_resolve_example_file`）——本文不重复。
- `ADDING_WORKFLOWS.md` 描述怎么**加工作流**，本文描述加完之后 UI 上**长成什么样**。
- 改两文档之一时，相应更新另一份。