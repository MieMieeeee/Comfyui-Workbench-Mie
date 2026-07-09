# UI_REWRITE_PROPOSAL.md -- Gradio 换成 FastAPI + HTMX + Tailwind？

> 2026-07-09 由作者提出，Codex 评估。**未决定，先看分析**。

## 0. 一句话结论

**不建议全量重写**。建议走中间方案 B（Gradio 加重度 CSS override + 主题）+ 单独抽出 status streaming / output 渲染层到 FastAPI 子服务。看下面三条路的对比。

---

## 1. 当前在用的栈

```
[Gradio 6.20]  ---> [FastAPI / uvicorn in scail2_client.py]
       |                     |
       |                     +---> [ComfyUI :8188]
       v
   浏览器
```

- `app/scail2_app.py` 一个文件 ~1600 行，承担表单渲染 + 状态机 + 输出渲染 + 三个 Tab + CSS 注入。
- `app/scail2_client.py` 封装 ComfyUI HTTP 通信（FastAPI 在这层已经跑着，只是不直接对外）。
- `app/history.py` 写 `app/data/runs/{id}.json`。
- `app/prompts.py` 提示词池。

测试：**152 passed in 8.17s**，包含 23 个 helper 单测 + e2e 渲染测试。

## 2. 现在痛在哪

| 痛 | 现状 | 影响 |
|---|---|---|
| 配色 / 间距 / 字体不够细 | Gradio 主题层级深、CSS override 只能覆盖部分 | 视觉上"工具感"重，"产品感"轻 |
| 排版自由度低 | `gr.Row` / `gr.Column` 12-grid 体系 | 想做的卡片化 / 不对称布局做不到 |
| 动画 / 交互细节 | Gradio 6 的 `gr.render` 已经够用，但复杂交互写不出 | e.g. 输出区的 hover / 拖拽排序 |
| 启动体积 | gradio-client + gradio + hf-gradio 等一大堆 | 装包 60+ MB |

其中**只有"配色 / 间距 / 字体"是用户提到的痛**。其余三条是衍生担忧，未必需要大动。

## 3. 三条候选路

### 方案 A：全量切到 FastAPI + HTMX + Tailwind

**架构**：

```
[Tailwind 编译产物] ---> [FastAPI :8199] ---> [Jinja2 模板]
                              |
                              +---> HTMX: 局部刷新 + SSE 推送状态
                              +---> ComfyUI :8188 (不变)
                              +---> app/history.py / app/prompts.py (不变)
```

**实现成本估算**：

| 块 | 工作量 | 备注 |
|---|---|---|
| 表单 schema 渲染（替代 `_render_workflow_form`） | 4-6 天 | 从 `params.json` schema 生成 HTML，每个 type 一个 Jinja macro；form 提交走 HTMX POST |
| 实时状态 / 进度推送（SSE 替代 `yield` + `progress`） | 2-3 天 | run 函数改成 async generator，前端 EventSource |
| 输出区（视频 / 图片 / 未知文件 fallback） | 1-2 天 | Jinja partial + `<video>` / `<img>` |
| 历史 tab + filter | 1-2 天 | Dataframe 换成手写表格 + HTMX 过滤 |
| 设置 tab + 健康检查 | 1 天 | 几乎不变 |
| CSS / Tailwind 配置 | 1-2 天 | 设计 token + 组件类 |
| **总计** | **10-15 天** | 假设一个人 + 完整时间 |

**丢的东西**：

1. **数据驱动表单生成的 90% 红利**。Gradio 的 `gr.File / gr.Image / gr.Video / gr.Slider / gr.Radio` 是组件级 API，写 `_build_input_component(spec)` 一处就吃遍所有 preset。换成 HTML 之后每个 type 要自己写 Jinja macro、事件绑定、表单序列化。**新增 type 的成本从 30 行 Python 涨到 ~100 行 HTML+JS**。
2. **152 个测试基本全部要重写**。Gradio 测试靠 Blocks 上下文 + `demo.blocks.values()`；HTTP 测试要装 `httpx.AsyncClient` + mock Form / SSE。
3. **bundle launcher 集成复杂度升一档**。gr.WebUI 是个进程，挂上 launcher 的 stdout / 重启逻辑很简单；FastAPI 还要管 uvicorn 生命周期。
4. **修复 bug 的反馈循环变慢**。Gradio 改 schema → reload → 浏览器立刻看到；Jinja + Tailwind 改完要重启 uvicorn（虽然用 `--reload` 也行，但 debug 体感差）。

**保留的东西**：

- 视觉自由度 100%（Tailwind + 自定义 CSS）
- 不依赖 Gradio 升级（Gradio 6→7 可能 breaking，6.20 之后是不是稳未可知）
- HTMX 学习曲线低，作者本人能维护

### 方案 B：Gradio + 重度 CSS override + 自定义主题（推荐）

**思路**：保留 Gradio 6 全部组件，只重写"皮肤"。

具体动作：

1. **去掉 Gradio 默认主题**。`gr.Blocks(theme=gr.themes.Base())` + 自写 CSS：
   - 暗色背景 `#0f1115`，卡片 `#1a1d23`，主色改成作者选定的 accent（暖橙 / 电光蓝 / 薄荷绿）
   - `gr.Button("primary")` 加重投影 + 圆角 + hover 渐变
   - `gr.Accordion` 用左 border-line 风格而非整块浅灰
   - `gr.Dataframe` 自定义 cell 渲染（status emoji / 时间格式化）
2. **改写 `_media_to_html` 输出区**（这层本来就是自己写的 HTML），加 Tailwind class 让图片 / 视频 hover 放大、画廊间距更松。
3. **左侧 Radio 换成 `gr.Button` + 自定义列表组件**（Gradio `gr.Dataset` 可以套上自定义 row template），让一行更紧凑、emoji 字号可调。
4. **CSS 文件抽出来**，放到 `app/static/style.css`，通过 `launch(css=...)` 注入。

**成本**：

| 块 | 工作量 |
|---|---|
| 设计 token + Tailwind 离线 build（产物一个 CSS 文件，**不用**装 node） | 0.5 天 |
| 改写 `build_ui` 注入 css + 把 `_media_to_html` / 左侧 Radio 用 Tailwind class 渲染 | 1-2 天 |
| 微调交互细节（hover / 状态过渡） | 1 天 |
| **总计** | **2-3 天** |

**保留的东西**：

- `params.json` schema → 表单渲染 的代码零改动
- 152 个测试**几乎不动**（可能加几个 CSS 类存在性测试）
- bundle launcher 集成零改动
- bug 反馈循环不变
- 数据驱动特性完整

**丢的东西**：

- 复杂交互动画写不出（Gradio 不支持 framer-motion 那种）
- 极致的视觉定制仍然受 Gradio DOM 结构限制（但 95% 视觉诉求都能做到）

### 方案 C：Gradio 嵌入 FastAPI，外层 FastAPI 做壳（折中）

**架构**：

```
[FastAPI :8199 (auth + 全局 layout + Tailwind)] 
       |
       +--- /         ---> 自写 index.html（顶部 bar + 左侧栏 + Tailwind 风格外壳）
       +--- /gr/...    ---> mount_gradio_app(Blocks)（表单 + 运行 + 历史 tab）
       +--- /api/...   ---> 状态 SSE / output 元数据
       +--- /static/   ---> 自写 CSS + 图标
```

**思路**：Gradio 当"组件运行时"挂在内层，外层 FastAPI 提供登录 / 全局导航 / 主题 / 自定义 404 页 / favicon。`mount_gradio_app` 是 Gradio 官方支持的模式。

**成本**：

| 块 | 工作量 |
|---|---|
| FastAPI 壳（路由 + middleware + mount_gradio_app） | 1-2 天 |
| index.html + Tailwind | 1 天 |
| 把 Gradio `launch()` 改成 `mount_gradio_app` | 0.5 天 |
| 状态 SSE 端点（如果想脱离 Gradio 推状态） | 1 天（可不做） |
| **总计** | **3-4 天** |

**保留**：

- 数据驱动表单完整
- 152 测试主体不动（可能要 mock `mount_gradio_app`）
- Tailwind 视觉自由

**丢**：

- 双进程心智（虽然都跑在同个 uvicorn 下，但要小心 Gradio 内部 state 和 FastAPI state 同步）
- 如果未来真的完全切走，迁移路径不干净（要先拆 Gradio 再拆 FastAPI 壳）

## 4. 决策矩阵

| 维度 | A 全量切 | B Gradio + 重度 CSS (推荐) | C Gradio 嵌 FastAPI |
|---|---|---|---|
| 视觉自由度 | ★★★★★ | ★★★★ | ★★★★★ |
| 实施时间 | 10-15 天 | **2-3 天** | 3-4 天 |
| 数据驱动特性保留 | ★★☆☆☆（要重写 schema 渲染） | ★★★★★ | ★★★★ |
| 测试改动量 | 几乎全重写 | 几乎不动 | 小改 |
| bundle 集成复杂度 | 高 | **零** | 中 |
| 长期维护成本 | 高（前端 + 后端） | 低（仍是 Gradio） | 中 |
| 与 `AGENTS.md` 数据驱动原则的契合 | **抵触** | **完全契合** | 折中 |

## 5. 我的建议

**走 B**。理由：

1. 你提的"gradio 不够好看"是**视觉问题**，不是**架构问题**。Gradio 6 主题可重写、CSS 可注入、组件 HTML 可包。
2. AGENTS.md 把"数据驱动、不动代码加工作流"写成核心原则。方案 A 把这个原则倒过来——以后加 type 要写 HTML 而不是 Python。
3. 152 个测试是过去 N 轮 TDD 的沉淀，方案 A 一刀切掉不划算。
4. bundle launcher 集成是你另一条独立产品线，方案 A 让那条线变重。
5. 2-3 天能看到效果；不满意再升级到 C 或 A 也是 OK 的演进路径。

**视觉方面**的几个具体下手点（先看看效果再说）：

- 主色 `#ff7849` 暖橙 → `bg-orange-500` 系（按 Tailwind token 命名）
- 卡片背景 `#1a1d23` → 自定义 `bg-surface` 类
- 字体统一 `font-sans` 用 system stack（避免 Web font 体积）
- 间距 8px 网格 → `gap-2 / gap-4 / p-3` 系列
- `gr.Button` primary → 加 `shadow-lg shadow-orange-500/30` hover 抬升
- 输出区图片加 `transition-transform hover:scale-105` 微动效

**风险**：Gradio 升级 7.x 时 CSS 类名可能变 → B 方案对升级敏感。缓解：把自定义 CSS 集中到一个文件，升级时 diff 这一个文件就够了。

## 6. 如果坚持 A，下面是一份落地骨架

> 这是**参考**，不直接动手。等你点头才动。

```
app/
  webapp/                      <- 新建
    __init__.py
    main.py                    <- FastAPI app + lifespan + mount_gradio_app
    routes/
      pages.py                 <- /, /healthz
      api_runs.py              <- POST /api/runs, GET /api/runs/{id} (SSE)
      api_history.py           <- GET /api/history (with filter params)
      api_health.py            <- GET /api/health (full check)
    templates/
      base.html                <- Tailwind + HTMX shell
      index.html               <- 左侧 Radio + 右侧 mount point
      partials/
        _run_form.html         <- 表单 Jinja macro (一个 type 一个)
        _output_gallery.html
        _history_row.html
        _status_dot.html
    static/
      style.css                <- Tailwind 编译产物
      app.js                   <- HTMX + Alpine/Tiny JS, < 200 行
    schemas.py                 <- Pydantic models (替代 gr.File 等)
    form_renderer.py           <- 从 params.json 生成 form HTML
    run_stream.py              <- async generator, 替代 _run_and_format 的 yield
  scail2_app.py                <- 保留，作为 form_renderer 的回退 schema 参考
  scail2_client.py             <- 不动
  ...                          <- 其余不动

requirements.txt               <- + fastapi, jinja2, uvicorn[standard], python-multipart, sse-starlette
                                <- - gradio (or 保留以便 C 方案过渡)
```

工作量：见 §3 方案 A 表。

## 7. 我需要你定的

1. **是否走 B？** 是 → 我把 CSS token 拿出来先出 1-2 个组件（按钮 + 卡片）的对比图给你看。否 → 进 §6 的 A 骨架详细规划。
2. 如果 A：是否要保留 Gradio 作为**开发期** schema 渲染的参考实现（写到 form_renderer 注释里），还是直接砍掉？
3. 如果 A：bundle launcher 那边你打算怎么挂这个新 webapp？是同一个 launcher 进程内 mount，还是独立进程？这影响 uvicorn 生命周期管不管。