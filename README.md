# ComfyUIWebToRunWorkflow

> 一个统一的多工作流 Web 前端 —— 把多个 ComfyUI workflow（文生图 / 图生图编辑 / 视频生成 / 表情迁移 / 语音克隆 / 音乐生成 等）包成一套带表单的网页。

> AI agent / 贡献者上下文：[`AGENTS.md`](./AGENTS.md)
> 怎么加新工作流：[`docs/ADDING_WORKFLOWS.md`](./docs/ADDING_WORKFLOWS.md)
> 架构 / 模块依赖：[`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)

## 这是什么

针对多个 ComfyUI workflow 做一个独立的多工作流 Web 前端：

- **用户视角**：左侧按组（图像 / 视频 / 音频）列工作流 + 描述，右侧动态表单（上传素材 / 填提示词 / 调参数 / 运行 / 看结果）。不需要看 ComfyUI 节点图。
- **背后**：本地 Flask 服务（端口 `8199`）+ Alpine.js 前端 + SSE 流式进度，通过 HTTP API 调本地 ComfyUI 实例（端口 `8188`）。
- **数据驱动**：表单完全从 `app/presets/definitions/<name>.json` 自动生成。加新工作流只动 definition JSON + workflow JSON + example 资产，**不动代码**。

## 快速开始

```bash
# 双击 bat（自动建/复用 .venv + 装依赖 + 启 Flask + 开浏览器）
start_webui.bat

# 或手动：
python -m venv .venv
.venv\Scripts\Activate.ps1          # PowerShell；bash/zsh 用 source .venv/bin/activate
python -m pip install -r requirements.txt
python -m app.flask_app
# 浏览器打开 http://localhost:8199
```

启动后：

1. WebUI 默认连 `http://127.0.0.1:8188` 的本地 ComfyUI。要改地址，去 **系统设置** tab 填 + 点"保存并测试"。
2. WebUI 与 ComfyUI 解耦：ComfyUI 没跑也能打开 WebUI；跑工作流前确保 ComfyUI 就绪。

## 目录结构

```
├── README.md                       本文件
├── AGENTS.md                       贡献者 / AI agent 指引
├── requirements.txt                Python 依赖
├── docs/
│   ├── ARCHITECTURE.md             架构图、模块依赖、API 契约
│   ├── ADDING_WORKFLOWS.md         加新工作流 recipe（必读）
│   ├── DECISIONS.md                关键决策记录
│   ├── UI_STYLE.md                 UI 约定（emoji / CSS 类 / 状态前缀）
│   └── plans/                      设计文档（migrate-to-flask / wizard 等）
├── app/
│   ├── flask_app.py                Flask 入口（路由 + API + SSE）
│   ├── config.py                   集中配置（路径 / 端口 / 阈值）
│   ├── scail2_client.py            ComfyUI HTTP API 封装（唯一碰 8188 的模块）
│   ├── health_check.py             用户部署环境诊断
│   ├── history.py                  历史 manifest sidecar
│   ├── workflow_validator.py       workflow 契约校验
│   ├── prompts.py                  提示词池
│   ├── presets/
│   │   └── definitions/           每 preset 一个 JSON: workflow 模板 + schema + example
│   │   ├── definitions/*.json      workflow 模板
│   │   └── health_requirements.json
│   ├── services/                   业务逻辑子模块（runner / form_schema / media / wizard / persistence / theme）
│   ├── templates/                  Jinja2 模板（base / run / settings / wizard）
│   └── static/                     CSS / JS / 主题 token / 示例预览
└── tests/                          pytest 单测 + Flask 路由 / SSE / 端到端
    └── _archive_gradio/            Gradio 版测试归档（有 README 说明原因）
```

## 已支持的工作流

完整列表见 `app/presets/definitions/*.json`，分类速览：

**图像**
- 文生图 (Z-Image-Turbo / Qwen Image 2512 / Anima / Krea-2)
- 图生图编辑 (Flux2 Klein Edit)
- 智能抠图 (SAM3)

**视频**
- 文生视频 / 图生视频 (LTX-2.3)
- 动作迁移 / 角色替换 (SCAIL2)
- 表情迁移 (LivePortrait)
- 智能抠视频 (SAM3)

**音频**
- 语音合成 / 语音克隆 (Qwen3-TTS)
- 音乐生成 (Ace Step 1.5)

每个 preset 在左侧导航按"图像 / 视频 / 音频 / 通用 / 其他"5 组折叠；每条都有 `description` + 加载示例 / 加载上次 / 最近输出 三个快捷按钮。

## 添加新工作流

1. 把 workflow JSON 拷到 `app/presets/definitions/<name>.json`
2. 在 `app/presets/definitions/<name>.json` 加 preset 配置（display_name / category / description / user_facing_inputs / example / preview）
3. 必要时改 `app/presets/health_requirements.json`（新模型 / 新自定义节点）
4. 跑一次 preset 生成 preview 图 / 视频，放到 `app/static/examples/<name>.*`，把路径写进 `definitions/<name>.json` 的 `preview_url`

完整字段表、调试项、example 写法见 [`docs/ADDING_WORKFLOWS.md`](./docs/ADDING_WORKFLOWS.md)。

## 测试

```bash
python -m pytest tests/ -v
```

E2E 浏览器渲染测试（默认不跑，需要 Playwright + Chromium）：

```bash
pip install -r requirements-dev.txt
playwright install chromium
python -m pytest tests/ --e2e -v
```

## 状态

持续维护中。当前已支持 15 个 workflow，313+ 单测 + 端到端。
