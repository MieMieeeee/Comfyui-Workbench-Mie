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
| 用相同参数再来 | 🔁 | 跑成功后出现的次按钮，hidden 在 success 前 |
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

只有三个自定义 class，在 `build_ui()` 末尾传给 `launch(css=...)`：

| class | 用在哪 | 视觉 |
| --- | --- | --- |
| `.error-banner` | 红条，跑失败 / 超时时显示 | 红底 + 黑字 |
| `.error-banner-inner` | `.error-banner` 内部 `gr.HTML` | 让 `gr.HTML` 占满 banner 容器 |
| `.file-fallback` | `_media_to_html` 未知文件类型 / 未知 URL | 灰底 + 下载链接 |

新增自定义样式前先想：**Gradio 默认主题能不能直接表达**。能就不加 class；不能再写
`css.append(...)`，并在本文档登记 class。

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

## 6. Tab 与布局

| Tab | 内容 |
| --- | --- |
| `运行` | 左侧 Radio + 搜索 + ComfyUI 状态指示；右侧 `gr.Group` 切换 preset 表单 |
| `历史记录` | Dataframe + Preset 过滤 + 状态过滤 + 详情面板（输入 / 输出 / 耗时 / cache） |
| `系统设置` | ComfyUI 地址 + 🔍 完整健康检查 + GPU/VRAM/模型/自定义节点报告 |

`运行` tab 默认选中。第一次切 preset 不请求网络（除 `🔍 完整健康检查` 外）。

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