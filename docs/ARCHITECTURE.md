# 系统架构

> 本文描述 comfyui-workbench-mie 的当前架构 (Flask 版, migrate-to-flask 2026-07-21 起).
> 早期 Gradio 版 (`scail2_app.py` + `params.json`) 已下线, 那段历史见 `docs/DECISIONS.md`.

## 总览

```
+-------------------------+        HTTP/SSE      +----------------------------+
|  浏览器 (用户)            | <-----------------> |  Flask WebUI (8199)         |
|  Alpine.js + SSE         |                     |  app/flask_app.py (路由)    |
|  - 上传素材              |                      |  app/services/* (业务)      |
|  - 填表单 / 调参数        |                     +-------------+--------------+
|  - 点运行 / 看结果        |                                   |
+-------------------------+                                   | HTTP (8188)
                                                              v
                                                +-------------------------+
                                                |  ComfyUI (8188)         |
                                                |  - /upload/image        |
                                                |  - /prompt              |
                                                |  - /history/{id}        |
                                                |  - /view?filename=...   |
                                                |  - /ws?clientId=...     |
                                                +-------------+-----------+
                                                              |
                                                              v
                                                +-------------------------+
                                                |  ComfyUI 文件系统        |
                                                |  - input/  (上传落盘)    |
                                                |  - output/<subfolder>/  |
                                                |    (生成媒体落盘)        |
                                                +-------------------------+
```

**两个独立进程**:

- `ComfyUI 启动器.exe` → 起 ComfyUI, 端口 8188 (**已存在, 不要碰**)
- `python -m app.flask_app` → 起 Flask WebUI, 端口 8199 (**本项目**; 避开 Gradio 默认 7860 和 ComfyUI 的 8188)

两者不共享内存, 只通过 HTTP + WebSocket (进度) + 磁盘文件交互. WebUI 跟 ComfyUI **解耦**: ComfyUI 挂了 WebUI 也能开 (用户在设置 tab 配 URL); WebUI 挂了不影响 ComfyUI.

---

## 模块依赖图

```
flask_app.py (Flask 路由: 页面 + API + SSE)
    │
    ├──> app/services/runner.py        运行编排 (run_workflow / run_image_workflow / stream_events)
    │       ├──> app/scail2_client.py  ★ 唯一跟 ComfyUI 8188 直接打交道的模块
    │       ├──> app/services/form_schema.py   表单 schema + 校验 + 文件解析
    │       ├──> app/services/status.py        状态字符串分类 (running/success/failure/timeout)
    │       ├──> app/services/media.py         media → HTML 渲染
    │       ├──> app/history.py                run manifest sidecar 写盘
    │       └──> app/workflow_validator.py     config drift 体检
    │
    ├──> app/services/wizard.py        工作流向导 (解析 workflow JSON + 推断输入 + 跑一次 + 存 preset)
    ├──> app/services/workflow_editor.py  已有工作流的输入布局 / 排序编辑
    ├──> app/services/theme.py         主题 + CSS 注入
    ├──> app/services/persistence.py   last_run 持久化
    ├──> app/health_check.py           层次化健康检查 (L0 连通 / L1 系统 / L2 模型 / L3 节点)
    ├──> app/config.py                 集中配置 (路径 / 端口 / 阈值 / preset_config)
    └──> app/prompts.py                随机提示词池
```

**核心边界**: `app/scail2_client.py` 是**唯一**跟 ComfyUI HTTP API 直接打交道的模块; 其它所有模块只通过它暴露的方法 (`upload` / `queue_prompt` / `get_history` / `wait_for_completion` / `get_output_url`) 调用. 这样 ComfyUI API 变化只动 client 一处.

---

## 数据驱动 —— 加工作流不动代码

表单完全从 `app/presets/definitions/<name>.json` 自动生成. 加新工作流只动数据 (definition JSON + workflow JSON + example 资产), **不动代码**. 完整 recipe 见 [`ADDING_WORKFLOWS.md`](./ADDING_WORKFLOWS.md).

单源: `config.preset_config(name)` 只读 `definitions/<name>.json`; `config.list_workflows()` 扫 `definitions/*.json`. 不再有 `params.json` (已下线).

每个 definition 的关键字段:

| 字段 | 用途 |
|---|---|
| `workflow_file` | 指向 `app/presets/<name>.json` (ComfyUI API 格式 workflow 模板) |
| `display_name` / `description` / `category` / `order` / `group` | UI 元信息 + nav 分组 |
| `user_facing_inputs` | 表单 schema 数组, 每条 spec 描述一个用户可改的字段 |
| `output_kind` | `image` / `video` / `audio` — 决定结果区渲染 |
| `example` | "加载示例" 按钮的默认值 + preview 资产路径 |
| `fixed_patches` | preset 级硬 patch (e.g. SCAIL-2 两种模式共用一个 workflow, 只在某个 node 不同) |

`user_facing_inputs` spec 的 `type` 决定渲染 + 运行时映射, 当前支持:
`file:image` / `file:video` / `file:audio` / `text` / `prompt_pool` / `select` /
`image_sizes` / `int` / `int_random` / `float` / `bool`. 加新 type 必须先在
`run.html` 模板 + `runner` 映射落地, 不要加半个能用的 type.

---

## ComfyUI HTTP API 契约

本项目用到的端点 (来自 ComfyUI `script_examples/basic_api_example.py`):

### 1. `POST /upload/image` — 上传文件

```
POST http://127.0.0.1:8188/upload/image
Content-Type: multipart/form-data
  image=@<file>     # form 字段名固定 "image", 但 body 可接受任意类型 (png/mp4/mp3...)
  type=input
  overwrite=true
```

返回: `{"name": "<ComfyUI 端文件名>", "subfolder": "...", "type": "input"}`

> ⚠️ 当前 ComfyUI 0.24 **只有 `/upload/image` 一个端点** (`/upload/file` 返 405). 它接受任意类型文件, form 字段名固定是 `image`. 见 `scail2_client.py` 的 `UPLOAD_ENDPOINT` 常量.

### 2. `POST /prompt` — 入队 workflow

```
POST http://127.0.0.1:8188/prompt
Content-Type: application/json
{"prompt": {<API 格式 workflow: node_id -> node_def>}, "client_id": "<uuid>"}
```

返回: `{"prompt_id": "<uuid>", "number": N}`

- `prompt` 字段是 **API 格式** workflow (不是 UI 格式), node id 当 key
- `client_id` 可选, 但有它能通过 WebSocket 收实时进度 (见下)

### 3. `GET /history/{prompt_id}` — 查执行状态

```
GET http://127.0.0.1:8188/history/<prompt_id>
```

返回 (节选):

```json
{
  "<prompt_id>": {
    "outputs": {
      "456": {
        "videos": [{"filename": "x.mp4", "subfolder": "SCAIL-2", "type": "output"}],
        "images": [{"filename": "y.png", "subfolder": "", "type": "output"}]
      }
    },
    "status": {"status_str": "success", "completed": true, "messages": [...]}
  }
}
```

`status.status_str` 取值: `success` / `error` / `failed` (方言). `status.completed` 为 `true` 表终态. node 崩溃时 ComfyUI 写 `{completed: false, status_str: 'error'}`, 轮询必须同时识别这两个终态判定 (见 `scail2_client.wait_for_completion` 的 `status_str in ("error", "failed")` 分支).

### 4. `GET /view` — 下载输出媒体

```
GET http://127.0.0.1:8188/view?filename=<name>&type=output&subfolder=<sub>
```

浏览器 `<img>`/`<video>` 直接吃这个 URL. 本项目通过同源代理路由 `/comfy_output` 转发它, 让局域网设备也能读 (见 `flask_app.py` 的 `comfy_output` 路由).

### 5. `WS /ws?clientId=<id>` — 实时进度

ComfyUI 通过 WebSocket 推送执行事件, 关键类型:

| `type` | `data` | 含义 |
|---|---|---|
| `progress` | `{value, max}` | KSampler/SamplerCustom step 进度 (e.g. 12/20) |
| `executing` | `{node}` | 某节点开始执行; `node == null` 表整个 prompt 完成 |
| `execution_cached` | `{nodes: [...]}` | 缓存命中跳过的节点 |
| `execution_error` | `{prompt_id, node_id, exception_message, ...}` | 节点崩溃 |

`scail2_client._ws_loop` 在 daemon 线程里跑 `asyncio.run`, 把事件塞进 `queue.Queue`; `wait_for_completion` 在 Flask 请求线程里 drain 队列, 把 step 进度叠加到状态消息里. websockets 缺失时静默降级到纯 HTTP 轮询 (AGENTS.md 信任模型: 失败不堆防御).

---

## workflow 参数替换 (patch)

每次运行, `runner` 按 `user_facing_inputs` 把用户输入映射成 `replacements: {node_id: {field: value}}`, 再调 `scail2_client.patch_workflow(wf, replacements)`:

- 深拷贝每个 node 的 `inputs` (顶层 `dict(v)` 不够, `node["inputs"]` 还是引用)
- 按 replacements 改对应 node 的 inputs 字段
- `validate_after=True` 时跑 `workflow_validator.validate` (config drift 体检)

复合 type 的映射:
- `image_sizes` → 一个 spec 拆成 `{width, height, batch_size}` 三个字段 (文生图多尺寸循环时每个尺寸各 patch 一次)
- `int_random` → UI 上是 [Checkbox + Number], 勾选时运行期 `random.randint`, 不勾用固定值
- `file:*` → 上传后取 ComfyUI input 目录下的纯文件名

`fixed_patches` (preset 级) 先于 user_facing_inputs 应用, 让 SCAIL-2 replace/motion 两种模式共用一个 workflow JSON.

### 表单值的两套索引 (别混用)

前后端之间传的 `form_values` 是**扁平数组**: 按 `user_facing_inputs` 顺序排, 每个 spec 占 1 格,
`int_random` 占 2 格 (随机勾 + 数值). `example_to_form_values` / `_manifest_to_form_values` /
`persistence._save_last_run` 都按这个约定产出/消费.

但页面内部的 `formValues` 是**按 spec 索引**存的 (模板里 `x-model="formValues[idx]"`, `idx` 就是
spec 在 `user_facing_inputs` 里的位置). 两者不是一回事: `int_random` 之后的字段, spec 索引比扁平
位置小 1. 混用会导致字段值整体错位一格 (issue #1: Z-Image-Turbo 的 VAE 收到 unet 的文件名,
ComfyUI 直接 400).

- 前端: `app.js` 的 `initPanelScope` / `_applyFormValues` 用扁平位置**读** `values`, 按 spec 索引**写**
  `formValues`; `collectFormValues` 再按 spec 顺序收回扁平数组.
- 后端: `runner` 的解析循环必须用两个计数器 —— spec 索引走 `user_facing_inputs`, 值索引走
  `form_values`. `int_random` 占 2 格, 不能把 spec 索引和值索引合成一个.

另外: 模型下拉框的选项 (`/api/preset_models`) 是异步到的, Alpine 的 `x-model` 在 `<option>`
渲染之前就把值写进 `<select>`, 那时选不中任何项, 浏览器会落回列表第一项 —— `app.js` 的
`_syncModelSelects` 负责在选项到位后把值摆正.

---

## 运行流 (SSE)

`POST /api/run/<preset>` 返回 `text/event-stream`, 每个事件一个 `data: {json}\n\n` 行, 末尾 `data: [DONE]\n\n` 哨兵. 流程:

```
flask_app.run_preset
  └─> runner.stream_events(preset, form_values, on_success)
        ├─ 选 run_fn: run_image_workflow (纯文生图) 或 run_workflow (其它)
        │   路由判定: output_kind=image + 有 image_sizes + 无 file 输入 → run_image_workflow
        │             否则 → run_workflow (支持全部 type + image output_kind)
        ├─ run_fn 是生成器, yield (status_msg, media) 流
        │   ├─ patch + queue_prompt
        │   ├─ start_progress_listener (开 ws 线程)
        │   ├─ wait_for_completion (轮询 + drain ws 进度, yield 状态)
        │   └─ extract outputs → 拼 view URL
        ├─ 每个 (status_msg, media) 包成 RunEvent (type=log/media/error/done)
        └─ 末尾必 yield 一个 done 事件 (即使失败)
```

状态消息前缀协议 (锁定, `status._extract_status_kind` 依赖):

- `⏳` 进行中 (waiting / running)
- `✅` 成功
- `❌` 失败 (connection / execution error)
- `⏰` 超时

---

## 持久化

| 路径 | 内容 | 模块 |
|---|---|---|
| `app/data/runs/*.json` | 每次 run 的 manifest (审计 / 历史 tab 数据源) | `app/history.py` |
| `app/data/last_run/<preset>.json` | 上次成功参数 (一键加载用) | `app/services/persistence.py` |
| `app/data/input_layouts/<preset>.json` | 用户自定义输入布局 (label/tier/help/顺序) | `app/services/workflow_editor.py` |
| `app/data/theme_settings.json` | 用户选的主题 | `app/services/theme.py` |
| `app/data/wizard/<token>.json` | 向导临时 workflow (parse 时存, save 时清) | `app/flask_app.py` |

runs/ last_run/ input_layouts/ wizard/ theme_settings.json 都在 `.gitignore` (per-machine 运行时状态). definitions/ themes.json health_requirements.json 是仓库资产 (随发布走).

---

## 健康检查 (分层诊断)

`app/health_check.py` 的 `check_health()` 做四层检查, 每层失败都给**可操作建议**:

| 层 | 检查 | 失败诊断 |
|---|---|---|
| L0 | `/system_stats` 连通性 | 区分端口没监听 / 超时 / 主机不可达, 给"去 ComfyUI launcher 点 Start" |
| L1 | GPU / VRAM / 版本 (从 system_stats 解析) | — |
| L2 | 模型文件 (`/object_info` 拿 loader 节点的可用文件) | "缺 X, 放到 ComfyUI/models/..." |
| L3 | 自定义节点 class_type (`/object_info.keys()`) | "缺 X 节点, 去 ComfyUI Manager 装 Y 包" |

L0 失败时报告写"workflow 本身已验证, 是你的 ComfyUI 实例不可用" —— 信任模型: 内建 workflow 是已知能跑的, 排查优先级是用户环境 > workflow.

---

## 部署

**本地开发** (当前阶段):

```
终端 1: ComfyUI 启动器.exe           (端口 8188, 已存在)
终端 2: start_webui.bat              (端口 8199, 自动建/复用 .venv + 装依赖 + 开浏览器)
```

`start_webui.bat` 会清掉占 8199 的旧 PID, 用 127.0.0.1 开浏览器 (避 IPv6 超时), 切 HF_HUB_OFFLINE.

**局域网共享**: Flask `host=0.0.0.0` 已监听所有网卡, Windows 防火墙放行 8199 即可. 注意 Flask 内置服务器 + 长时 SSE 连接的并发上限 (几十个并发 run 可能耗尽线程), 适合小范围演示, 不适合公网.

**公网部署**: 当前未支持. 真要部署建议换 waitress/gunicorn + 反代 (Cloudflare Tunnel / ngrok).
