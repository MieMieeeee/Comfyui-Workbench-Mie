# ComfyUIWebToRunWorkflow

> 把多个 ComfyUI 工作流（SCAIL-2 循环换脸、Z-Image-Turbo 文生图等）包成统一的多工作流 Web 界面。

> AI agent 上下文见 [`AGENTS.md`](./AGENTS.md)；怎么加新工作流见 [`docs/ADDING_WORKFLOWS.md`](./docs/ADDING_WORKFLOWS.md)。
> 用户不需要看 ComfyUI 节点图，左侧选工作流、右侧填表单、按运行。

## 这是什么

针对多个 ComfyUI workflow 做一个独立的多工作流 Web 前端。核心目标：

- **用户看到的 UI**：左侧工作流列表，右侧动态表单（上传素材 / 填提示词 / 调参数 / 运行 / 看结果）
- **背后跑的**：ComfyUI 实例（端口 8188），由 Web 前端调 `/upload` + `/prompt` + `/history` + `/view`
- **schema 驱动**：表单完全从 `app/presets/params.json` 自动生成，加新工作流只需加 preset + workflow JSON，**不改代码**
- **选 Gradio**（Python 写、不碰 JS），后续视情况升级到 HTMX + FastAPI 或 Vue + FastAPI

## 目录结构

```
F:\ComfyUIWebToRunWorkflow\
├── README.md                       ← 本文件
├── requirements.txt                ← Python 依赖（gradio / requests / pytest）
├── docs\
│   ├── PLAN.md                     ← 实施计划（阶段、里程碑、验收）
│   ├── ARCHITECTURE.md             ← 系统架构图、文件依赖、API 契约
│   ├── DECISIONS.md                ← 决策记录
│   └── ADDING_WORKFLOWS.md         ← 新增工作流 recipe（必读）
├── app\
│   ├── scail2_app.py               ← Gradio 入口（多工作流 UI + 动态表单）
│   ├── scail2_client.py            ← ComfyUI HTTP API 封装（唯一碰 8188 的模块）
│   ├── workflow_validator.py       ← workflow 契约校验
│   ├── history.py                  ← 历史 manifest 读写
│   ├── prompts.py                  ← 提示词池（随机/手填）
│   ├── config.py                   ← 集中配置（路径/端口/阈值）
│   ├── presets\
│   │   ├── params.json             ← 所有 preset 的 schema（UI 表单 + 节点映射 + tier 分层 + example）
│   │   ├── scail2_motion_transfer_final.json ← SCAIL-2 动作迁移 / 角色替换共用 workflow
│   │   ├── zimage.json             ← Z-Image-Turbo 文生图 workflow
│   │   └── prompts.json            ← 文生图提示词池（22 条精选）
│   └── data\runs\                  ← 每次运行的 manifest sidecar
├── tests\                          ← pytest 单元测试 + 端到端冒烟脚本
└── notes\                          ← 实施笔记
```

## 涉及到的已有资源（**只读，不要改**）

| 资源 | 路径 | 作用 |
|---|---|---|
| ComfyUI 实例 | `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI` | 端口 8188，后端服务 |
| ComfyUI 输入目录 | `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\input` | 上传文件落盘 |
| ComfyUI 输出目录 | `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\output` | 生成视频落盘 |
| SCAIL-2 最终 workflow | `E:\cc\data\scail2\workflows\wan21_scail2_loop_tutorial_final.json` | 60 节点版（无 cache） |
| SCAIL-2 cache workflow | `C:\Users\administered\Downloads\wan21_scail2_loop_fixed_canvas_cached_final.json` | 79 节点版（StringFormat + LoadOrCompute 缓存） |
| 调研笔记 | `E:\cc\data\scail2\notes\` | t01-t28 完整背景 |
| 现有 queue 脚本 | `E:\cc\data\scail2\scripts\queue_*.js` | 参考实现，可重用 HTTP 调用模式 |

## 快速开始

```bash
# 方式一：双击 bat（自动装依赖 + 启 Gradio + 开浏览器）
start_webui.bat

# 方式二：手动（推荐用项目内 .venv，依赖隔离，方便后续合进整合包）
python -m venv .venv
.venv\Scripts\Activate.ps1          # PowerShell; bash/zsh 用 source .venv/bin/activate
python -m pip install -r requirements.txt
python app/scail2_app.py
# 浏览器打开 http://localhost:8199
```

### 为什么带 `.venv`

这个项目最终会被整合包 launcher 拉走、和它自带的 embedded Python 合并。
本地 `.venv` 锁住"开发期 Python 版本 + 依赖集合",launcher 拿走的就
是同一份可重现环境。`.venv/` 已经在 `.gitignore`,每个开发者 / CI 各自
重建。

ComfyUI 地址**不需要**在启动前配置 —— WebUI 打开后去"设置" tab 填地址、点"保存并测试"即可（默认 `127.0.0.1:8188`，可改成局域网/远程实例）。WebUI 与 ComfyUI 解耦：ComfyUI 没跑也能打开 WebUI，跑工作流前再确保 ComfyUI 就绪。

## 支持的工作流

界面采用**卡片式步骤布局**：左侧工作流卡片导航（带描述），右侧步骤式表单。

```
┌─────────────┬──────────────────────────────────────┐
│ 🎬 工作流    │ SCAIL2 角色替换                       │
│ ●角色替换    │ 把参考图角色替换到驱动视频...           │
│ ○动作迁移    │ [📥 加载示例素材（一键填表）]          │
│ ○文生图      │ ┌─ ① 输入素材 ──────────────────┐    │
│             │ │ 参考图上传  [缩略图预览]         │    │
│ ComfyUI:    │ │ 驱动视频上传 [视频预览]         │    │
│ 127.0.0.1   │ └───────────────────────────────┘    │
│             │ ┌─ ② 参数 ──────────────────────┐    │
│             │ │ 主提示词                        │    │
│             │ └───────────────────────────────┘    │
│             │ ▸ 🔧 高级参数（一般不用改）           │
│             │ [🚀 开始运行]                        │
│             │ ┌─ 生成结果 ────────────────────┐    │
│             │ │ (视频/图片画廊)                 │    │
│             │ └───────────────────────────────┘    │
└─────────────┴──────────────────────────────────────┘
```

- **深色主题**（`#111315` 背景 + `#1b1d22` 卡片分层），橙色主色
- **📥 加载示例素材**：表单顶部一键填入预设素材（参考图/驱动视频取自 ComfyUI input 目录，自动解析成绝对路径，跳过上传）
- **高级参数折叠**：SAM3 主体识别词、段长、pre-drop 等进 `🔧 高级参数` Accordion（默认收起，不干扰主流程）
- **状态精简**：顶部 1 行状态文字 + `gr.Progress` 真实进度条（百分比+描述）
- **步骤分区**：① 输入素材 → ② 参数 → 高级参数 → 🚀 运行 → 结果

| 工作流 | preset | 说明 |
|---|---|---|
| SCAIL2 角色替换 | `sca12_replace` | 把参考图角色替换到驱动视频（node 353=true） |
| SCAIL2 动作迁移 | `sca12_motion` | 把驱动视频动作迁移到参考图角色（node 353=false） |
| 文生图 (Z-Image-Turbo) | `zimage` | 文生图，9 节点，支持随机提示词 + 多尺寸批量 |

SCAIL2 两种模式由 workflow 内 node 353 (PrimitiveBoolean `replacement_mode`) 控制，通过 preset 的 `fixed_patches` 字段固定，无需改 workflow JSON。每个输入字段在 `params.json` 标注 `tier: "basic"|"advanced"` 决定它在基础区还是高级折叠区。

新增工作流：只动三个数据文件 + 一轮验证、**不动代码**。详细步骤、字段表、调试项 见 `docs/ADDING_WORKFLOWS.md`。

运行时进度条按步骤推进：上传参考图(10%) → 上传驱动视频(20%) → 组装 workflow(30%) → 入队(40%) → 等待执行(45%→92%) → 完成(100%)。文生图多尺寸按 `第 i/N 张` 比例分配。

## ⚙️ 设置

"设置" tab 配置 ComfyUI 连接：

- **ComfyUI URL**：默认 `http://127.0.0.1:8188`，可填远程/局域网地址（如 `http://192.168.1.100:8188`）
- **保存并测试**：写入运行时状态 + 立即调 `/system_stats` 验证连通性
- **恢复默认**：回到 config 里的 `COMFY_BASE_URL`（支持 `COMFY_BASE_URL` 环境变量覆盖）
- **重新测试**：不改变地址，只重测连通性

地址运行时可改 —— 改完即时生效（所有上传/入队/历史调用都走当前地址），无需重启 WebUI。

文生图提示词池：`app/presets/prompts.json`（22 条精选提示词，10 个类别）。手动编辑该文件即可扩充；UI 上点"🎲 随机提示词"从池中抽一条。

## 测试

```bash
python -m pytest tests/ -v
```

### E2E 浏览器渲染测试

有一组用真实 Chromium 加载页面的 E2E 测试（锁定"页面永久加载中"类前端 regression），默认不跑：

```bash
# 首次需装 playwright + 浏览器（开发期依赖，不进整合包）
pip install -r requirements-dev.txt
playwright install chromium

# 跑 E2E（加 --e2e 标志）
python -m pytest tests/ --e2e -v
```

## 状态

- [x] 项目目录建立
- [x] 阶段 0：ComfyUI HTTP API 探活 + 模板落地 + config
- [x] 阶段 1：Gradio 骨架（schema 驱动表单 + 输入校验）
- [x] 阶段 2：cache 版切换（params.json 双 preset）
- [x] 阶段 3：历史 tab（manifest sidecar）
- [x] 阶段 4：错误处理与进度美化
- [x] **多工作流架构**：左侧列表 + 右侧动态表单
- [x] **文生图工作流**（Z-Image-Turbo + 提示词池 + 多尺寸）
- [x] **TDD 修复**：patch 污染 bug / `_max_idx` 重复 / `_update_est` 耦合 / `yielded_done` dead code / UTF-8 重存