# AGENTS.md -- ComfyUIWebToRunWorkflow

> 给贡献者 / AI agent 的项目级指引。
> 工具层 (shell / 转义 / 排查) 见顶层 `~/.codex/AGENTS.md`；
> 这个文件只覆盖项目方向与惯例。

## 这是什么

本项目是 [ComfyUI](https://github.com/comfyanonymous/ComfyUI) 集成套件的**配套多工作流 Web 前端**：
- 后端跑在 Flask (`app/flask_app.py`, 端口 `8199`)
- 前端是 Alpine.js + SSE (`app/static/app.js`, `app/templates/`)
- 通过 HTTP API 调本地 ComfyUI 实例（端口 `8188`）
- **不**是独立产品。`app/presets/` 下所有 workflow 都是作者预审过的，不是用户上传的第三方内容。

完整架构、数据流、模块依赖见 [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)。

## 信任模型 —— 这条决定很多代码方向

**内建 workflow 是已知能跑的。**

- 不要假设 workflow 在运行时缺插件 / 缺节点。`app/workflow_validator.py` 只做 **config drift 体检**（`definitions/<name>.json` 跟 workflow JSON 不一致），不是 plugin-availability 闸门。
- `app/health_check.py` L2/L3（模型 / custom nodes）检查的是**用户部署环境**（这台机器的 ComfyUI 缺什么），不是 workflow 本身的可信度。报错文案要写「你的 ComfyUI 实例缺 X」，不是「workflow 需要 X，我们没装」。
- 排错优先级（决定 debug 路径）：
  1. 用户输入（参数 / 文件大小 / 提示词长度）
  2. ComfyUI 进程 / 端口状态
  3. 资源（VRAM / 磁盘 / 文件大小限制）
  4. **最后**才怀疑 workflow 本身

加新的 preflight / auto-recovery / fallback 时，不要在「插件可能缺」假设上叠防御层。

## 添加新 workflow（数据驱动，不写代码）

加一个工作流只动数据，不动代码。完整 recipe 见 [`docs/ADDING_WORKFLOWS.md`](./docs/ADDING_WORKFLOWS.md)。

| 文件 | 改什么 |
|---|---|
| `app/presets/definitions/<name>.json` | workflow 模板本身 |
| `app/presets/definitions/<name>.json` | preset 配置（display_name / category / group / description / user_facing_inputs / example） |
| `app/presets/health_requirements.json` | 只有 workflow 加了新模型 / 自定义节点时才动 |

**新 type 不在已有 schema 范围内**：先在 `_build_input_component` 扩展类型支持，再让作者在 definition 里用。**不要**为一个 workflow 写一次性 bypass 路径。

`example` 字段每个 preset 都必须有 —— 它是用户打开工作流后**第一眼看到**的参数，也是切到该 preset 时的默认值。这条由 `tests/test_preset_must_have_example.py` 锁住。

## 多输出节点的选择 —— 不确定就问作者

workflow 有多个 image / video 输出节点时，runner 要挑一个显示在结果区。不要猜。

**默认协议**：打开 workflow JSON，找出所有 output-capable 节点，看 `_meta.title`（`SaveImage` / `PreviewImage` / `VHS_VideoCombine` 等）、是否写 `output/`（`type="output"`）还是 `temp/`、是中间 mask 还是最终 render。

- 答案能从 title + storage type 推出来 → 直接在 definition 里标（比如 `do_not_modify_warnings` 写明「node N = 最终用户输出」）
- 不确定（比如一个 workflow 有 3 个 PreviewImage + 1 个 SaveImage 分不清哪个是结果）→ **停，问作者**

写明具体问题：
> "这个 workflow 在节点 X / Y / Z 有 image 输出，哪个是用户在结果区应该看到的？"

> "我根据 <理由> 认定 node N 是最终 image，确认后我锁定。"

这条 image-output 选择发生在 `app/scail2_client.py` 的一个 chokepoint。挑错默认会静默显示错图（比如 SAM mask 而不是 wordcloud），用户以为 workflow 坏了。

## Schema 设计方向 —— 降低作者负担

`user_facing_inputs` 数组每条要填 (node_id / field / label / type / tier)。这是项目里**最重的作者负担**。几个收敛方向值得追：

- `type` 大多能从 workflow JSON 推（`file:image` / `file:video` / `text` / `int` / `bool` / `image_sizes`）。任何减字段的方向都是好事。
- 加新 type 时，**先**在 `_build_input_component` 落地，**再**让作者用。**不要**加半个能用的 type —— 当前 `image_sizes` 的「自定义 WxH 逗号分隔」分支 UI 不可达，半成品应该清掉。
- `do_not_modify_warnings` 是给未来维护者的备忘，不是用户配置 —— 保持轻量。
- `fixed_patches` 是 preset 级硬 patch（比如 SCAIL2 两种模式共用一个 workflow JSON，只在 node 353 不同）。这个复用机制很好，鼓励新 workflow 用。

## 本地开发环境 —— `.venv`

项目用本地 `.venv/` (Python 3.12.10)，不能依赖系统 pip。

- `.venv/` 在 `.gitignore`，每人从 `requirements.txt` 重建
- 跑测试用 `.venv\Scripts\python.exe -m pytest tests -q`
- 加新依赖必须写进 `requirements.txt`，**并**验证从干净 venv 能 `pip install -r requirements.txt`
- `start_webui.bat` 自动建 / 复用 `.venv` 并从里启动 —— 不要改这个行为

## 跟 launcher 的关系

- 端口 **8199** —— 避开 Gradio 默认 7860 和 ComfyUI 8188
- WebUI 跟 ComfyUI 解耦：WebUI 挂了不影响 ComfyUI；ComfyUI 挂了 WebUI 也能开（用户在 Settings tab 配 URL）
- Health check 失败必须给**可执行诊断**（端口没监听 → "去 ComfyUI launcher 点 Start"；模型缺 → "放到 ComfyUI/models/..."），不能只说 "连不上"
- `start_webui.bat` 启动前会清掉占 8199 的 PID 并自动 pip install —— 不要改

## 防御层 —— 不要轻易拿掉

| 模块 | 守的 |
|---|---|
| `app/workflow_validator.py` | config drift（definition 跟 workflow JSON 不一致） |
| `app/health_check.py` | 用户部署环境诊断（L0 连接 / L1 系统 / L2 模型 / L3 节点） |
| `app/history.py` | 每次运行 manifest sidecar（审计 / 历史 tab 数据源） |
| `app/services/runner.py` | 运行编排 + 多输出节点选择 |
| `app/services/form_schema.py` | 表单 schema 渲染 + example → form values 映射 |
| `app/services/media.py` | 文件 / 视频 / 音频 HTML 渲染（覆盖 ComfyUI /view URL 这种带 query 的） |
| `app/services/workflow_editor.py` | wizard 编辑工作流（保存 → 重排 → 写 definition） |
| `app/services/persistence.py` | `last_run.json` / 用户输入布局持久化 |

## UI 约定

emoji 调色板（🎬/🖼️/🔊 等）、tab 结构、`last_run` 状态持久化、CSS 类清单都在
[`docs/UI_STYLE.md`](./docs/UI_STYLE.md)。加新按钮、状态前缀、分类前先在那里登记。

## 编辑 checklist

- 提「加个防御检查」之前问：这假设在信任模型下成立吗？不成立就跳过。
- 提「重写这个 helper」之前看 `docs/DECISIONS.md` —— 每条决策都有 rationale。
- 提「拆这个模块」之前查数据驱动原则是否禁止 —— 新功能应该只动数据，不加模块。
- 写新文案 / 帮助文字时用**用户视角**（用户不知道 node ID 367 是什么），永远不要在 UI 文案里漏 node 数字。
