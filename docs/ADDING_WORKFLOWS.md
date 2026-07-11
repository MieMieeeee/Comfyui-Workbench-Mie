# ADDING_WORKFLOWS.md — 新增工作流程

> 伴随 `AGENTS.md` 的信任模型。内置 workflow = 已知能跑。本文档是作者本人下次要加新工作流时的参考清单。
> UI 上长成什么样 (左侧 emoji 前缀 / 按钮配色 / 状态前缀 / CSS class) 不在本节,在 [`docs/UI_STYLE.md`](./UI_STYLE.md)。

## TL;DR

加一个 workflow = 只动三个数据文件 + 一轮验证。**不动代码**。

1. 放入 `app/presets/{name}.json`(workflow 模板)
2. 在 `app/presets/params.json` 里加 preset 配置
3. 若引入新模型 / 自定义节点 → 追加 `app/presets/health_requirements.json`
4. `python -m pytest tests/ -q` 全绿 -> `python app/scail2_app.py` 手动看一眼

---

## 步骤 1 — 准备 workflow 模板

从 ComfyUI 导出 API 格式 workflow JSON,**原样复制**到 `app/presets/{name}.json`。

- **命名**: 小写 + 下划线,比如 `t2v_anime_v2.json` 、`controlnet_qr.json`
- **不动** workflow 本体(ComfyUI 导出是对的,节点 ID 是真实索引),不动 node title
- 一份 workflow JSON 可被多 preset 共享 — 这些 preset 都用 `workflow_file` 字段指回同一份 JSON 文件。参考:sca12_replace / sca12_motion 共用同一份 `sca12_uncached.json`,只 patch node 353 切换 mode。

## 步骤 2 — 在 params.json 加一条 preset

在 `app/presets/params.json` 的 `presets` 字典里加一个新 key。以下是完整字段说明 + 一个 real-example。

### 2.1 完整字段清单

```json
{
  "<your_preset_name>": {
    "display_name": "中文显示名",
    "category": "video | image | other",
    "order": 30,
    "description": "一句话介绍,用用户看得懂的话",
    "workflow_file": "<your_preset_name>.json",

    "fixed_patches": {
      "<node_id>": { "<field>": <value> }
    },

    "user_facing_inputs": [
      {
        "node_id": "<node_id>",
        "field": "<input_field>",
        "label": "中文标签",
        "type": "file:image | file:video | text | prompt_pool | int | bool | image_sizes",
        "tier": "basic | advanced",
        "default": "...",
        "help": "...",
        "min": 1, "max": 100, "step": 1
      }
    ],

    "example": {
      "reference_image": "示例图名.png",
      "drive_video": "示例视频.mp4",
      "ref_prompt": "human",
      "drive_prompt": "human",
      "main_prompt": "...主提示词...",
      "segments": 3,
      "prompt": "...zimage 示例提示词..."
    },

    "output_kind": "image",

    "do_not_modify_warnings": [
      { "node_id": "503", "reason": "段间色阶校色" }
    ]
  }
}
```

① `display_name` / `description` 是用户看到的,请用用户视角的词。不要泄露 node_id。
② `category` 仅用于后台分组与渲染顺序,默认 `"other"`。
③ `order` 越小越靠前。已有: 10 / 20 / 30 。在它们之间插值如 25 。

### 2.2 `type` 怎么选 — 从 workflow 推断

`type` 不需要你手查文档。以下是当前 `_build_input_component` 支持的全集 + 推断规则:

| 节点 class_type | field | type | UI 呈现 |
| --- | --- | --- | --- |
| `LoadImage` | `image` | `file:image` | 上传 + 缩略图预览 |
| `VHS_LoadVideo` / `LoadVideo` | `video` | `file:video` | 上传 + 视频预览 |
| `CLIPTextEncode` / `PrimitiveString` | `text` | `text` | 文本框 |
| 任何 `CLIPTextEncode.text` 是主提示词 → 改为 `prompt_pool` | `text` | `prompt_pool` | 文本框 + "🎲 随机提示词" 按钮 |
| `PrimitiveInt` / int slider / `int_range_end` | value | `int` | 滑块 (min/max/step) |
| `PrimitiveBoolean` | `value` | `bool` | 复选框 |
| `EmptySD3LatentImage` / `EmptyLatentImage` | `width` / `height` | `image_sizes` | 多选预设尺寸(每个出一张) |
| `MieLoopParamGetInt|Mie` / `*GetFloat|Mie` | value | `int` | 滑块 |
| 另外:**纯输出节点不需要** user_facing_inputs(例如 `VHS_VideoCombine`, `SaveImage`) | | | |

推断不出来 → 先 在 `app/scail2_app.py:_build_input_component` 里加这个 type,再在 params.json 用。不要加“半工作”的 type 后留下不能走到的分支。

### 2.3 `tier` 怎么选

- `basic` — 默认显示在主区域(用户每次都要改的字段)
- `advanced` — 折叠进 🔧 高级参数面板

判断: **90% 用户用默认值就不动** 的字段 → `advanced`。

> emoji / 配色 / 按钮前缀等视觉约定见 [`docs/UI_STYLE.md`](./UI_STYLE.md) §2、§3、§5。加新 type 时,UI 这一侧会自动按当前 palette 渲染,不需要在这里另写文档。

参考 SCAIL-2:主提示词 `basic`,ref_prompt / drive_prompt / frames_per_segment / pre_drop / max_segments 都是 `advanced`。

### 2.4 `example` 怎么写

“加载示例资料”按钮是这里填的。当前与 example key 的约定如下:

| example key | 填哪个组件 |
| --- | --- |
| `reference_image` | 所有 `file:image` 字段 |
| `drive_video` | 所有 `file:video` 字段 |
| `ref_prompt` | `node_id=362` 的 `text` |
| `drive_prompt` | `node_id=348` 的 `text` |
| `main_prompt` | `node_id=360` 的 `text` |
| `segments` | `node_id=479` 的 int |
| `prompt` | `prompt_pool` 的文本框 |
| `sizes` | `image_sizes` 的多选框(预设数组,如 `["720x1280"]`) |
| `preview_image` | 想要在右栏"示例预览"卡里展示的结果图(项目内路径或 URL) |
| `preview_caption` | `preview_image` 下方一行说明 |

文件值自动从 `config.COMFY_INPUT_DIR` 找(只要你把示例放到该目录就行),然后 stage 到项目内 `.examples_cache/` (Gradio 6 安全限制)。

#### 示例预览卡(可选)

想让用户在未运行前就看到"这个 preset 跑出来是什么样",在 `example` 里加这三个 key:

- `preview_image`:项目内路径(推荐)或外部 URL。**项目内路径走 `/file=` 路由**,把图 commit 进 `app/static/examples/`(命名 `{preset}_{size_slug}_{counter}.png`,例:`zimage_720x1280_0001.png`)。
- `preview_caption`:一行说明,例如 `🖼 720×1280 ｜ 9:16 ｜ 黄裙森林光影`。
- `sizes`:这个示例跑的尺寸,会填到 `image_sizes` 多选框里,也会在预览卡上方一行小灰字展示。

UI 行为:右栏顶部常驻一个"示例预览"卡(只有当 `preview_image` 存在时才显示)。点 "📥 加载示例素材" 会同时把表单字段和预览卡一起同步。

> `preview_image` 推荐项目内路径——便于 commit、可离线、跟工作流绑定。如果必须用外部 URL(如 ComfyUI 实例 `/view` 直链),要明确标注"仅本机可访问",不要写进 README 当作通用引用。

> SCAIL-2 两个 preset 采用 hardcoded 的 `362 / 348 / 360 / 479` node_id 是 SCAIL-2 workflow 内部约定。你的新 workflow 不一定这些 node_id — 照你 workflow 实际的 node_id 写 `user_facing_inputs` 即可。example 的 key 不能全部都用上,不能对上的字段简单留空。

### 2.5 `fixed_patches` 怎么写

Preset 自带的固定 patch,入队前**先** 应用。适用场景:

- 同一份 workflow JSON 被多 preset 复用(例:sca12_replace / sca12_motion 共享 `sca12_uncached.json`, 仅 patch node 353 切换 mode)
- preset 想覆盖 workflow 里的某个默认值,但不想让用户每次都改

格式跟 `user_facing_inputs` 的 `replacements` 一致。

### 2.6 `do_not_modify_warnings` 怎么写

给接手者看的备忘,不是用户配置。主要起到提醒“这个节点动之前先想明白”。

### 2.7 `also_patch`: 同一份素材绑多个 node

典型场景:SCAIL2 的 `node 369` (Drive Slice, 按段切驱动视频) 和 `node 469` (Full Source, 取整段视频的音频 + 元信息)
**必须绑同一份视频**。否则音频丢失 / 帧数不匹配 / `MieLoopEnd` 报 `Start index is out of range`。

**这是 schema 层 (不是新代码) 的解决方案**:
在 `user_facing_inputs` 的 `file:video` 项上挂一个 `also_patch` 列表,运行时会自动把同一份 `drive_name` 写到列表里的每个 node。

格式:

```json
{
  "node_id": "369",
  "field": "video",
  "label": "驱动视频",
  "type": "file:video",
  "tier": "basic",
  "also_patch": [{"node_id": "469", "field": "video"}],
  "also_patch_reason": "node 469 取音频 + 元信息,必须和 node 369 用同一份"
}
```

- `also_patch` 可选;缺省 / `[]` 退化为只 patch 主 node (旧 preset 兼容)
- 每项形如 `{"node_id": "...", "field": "..."}`;同一份 `drive_name` 写到 `replacements[enid][efield]`
- 主 node id 又出现在 `also_patch` 不会丢主字段 (覆盖写同名,值相同)
- `workflow_validator` **不**校验 `also_patch` 列出的 node 是否存在 (它的存在性由运行时 `patch_workflow` 隐式覆盖 inputs 来保证)
- `also_patch_reason` 是给未来维护者看的备忘,不是运行时逻辑

什么时候**不**需要 `also_patch`:

- 只有 1 个 node 拿这份视频 → 不需要
- 多个 node 但拿不同视频 → 每个 node 各自开一个 `file:video` 项,不要用 `also_patch`
- patch 一个非视频字段 → 用 `fixed_patches` (preset 级),不是 `also_patch` (user_facing 级)

## 步骤 3 — 引入新模型 / 节点 → 追加 health_requirements.json

只有新 workflow 用了**现有 health_requirements.json 里没有**的模型 / 节点依赖时,才需要追加。已有节点复用即可
(所有 ComfyUI-MieNodes 节点、常见 loader 都在里面)。

追加格式:

```jsonc
{
  "models": [
    {"node": "UNETLoader", "field": "unet_name", "filename": "X/y.safetensors", "folder": "diffusion_models", "workflows": ["<your_preset>"]}
  ],
  "custom_nodes": [
    {"class_type": "NewNodeClass", "package": "comfyui-x-package", "workflows": ["<your_preset>"]}
  ]
}
```

## 步骤 4 — 验证

三轮检查:

1. `python -m pytest tests/ -q` — 应全绿。报错意味着 params.json 与 workflow 存在契约漂移,按报错修。
2. `python app/scail2_app.py` — 启动日志里的 preflight 会打印 preset 状态。三个 preset 都“OK”才算过。
3. 手动: 浏览器开 `http://localhost:8199`,左侧应出现你加的 workflow 。点“加载示例资料” — 表单应一键填满。点“开始运行” — 能拿到输出。

运行失败排查顺序(参考 AGENTS.md 信任模型):

1. 用户输入(参数、文件大小、提示词长度)
2. ComfyUI 进程 / 端口状态(到"系统设置" tab 点“完整健康检查”看报告)
3. 资源(VRAM、磁盘、文件大小上限)
4. 最后才怀疑 workflow 本身

“最后怀疑” = workflow 在你环境能跑通、只是某个表单字段传错了类型在 user_facing_inputs 里。修 params.json,不动代码。

## 实操上最高频: 一份 workflow 衍生多个 preset

想要给同一份 workflow 衍生多个 preset 变体(为不同场景用不同默认值、不同 fix),是最高频的加工作场景之一。零代码改动的做法: 多个 preset key,全部 `workflow_file` 同一个 JSON,仅在 `fixed_patches` 和 `user_facing_inputs` 上不同。

例:

- SCAIL-2 角色替换 = `fixed_patches.353 = false`
- SCAIL-2 动作迁移 = `fixed_patches.353 = true`
- 你可能要加 `SCAIL2 高清版`,只换 `fixed_patches` 中某些参数 + `user_facing_inputs` 中增加一个 `qwen_edit` int 控制强度,代码零变动。

## 实操视角: 加完后会看到什么

- `app/data/runs/` 下出现你这个 preset 的运行 manifest。点“历史记录” tab 可看到。
- 如果你加了新节点或模型,“完整健康检查”里会出现它们。
- Preset 名称出现在 `工作流 选择卡片` 左侧,按 `order` 排序。
- `加载示例资料` 按钮可用 — 只要你填了 `example` 。

代码侧 **什么都不会** 变。

## 几条口诀

- **节点 ID 写错** → `workflow_validator.validate` 会报 "missing node X" 。这是契约漂移侦测,**不要** 绕过。
- **field 名写错** → 同上,但报错信息是 "missing inputs.X"。
- **示例文件不在 ComfyUI input 目录** → "加载示例"按钮不填 file 字段(其它字段仍填),用户手动上传。不是 bug,是 fallback。
- **同一份 workflow 多 preset 共享** → 用 `workflow_file` 显式指明,别依赖默认。
- **新工作流需新 type** → 走 "拓 schema" 路径(`_build_input_component` 先加,再用),不要单独写代码。
- **新工作流用了列表里没有的模型 / 节点** → 记得追 `health_requirements.json` 里的 `models` 或 `custom_nodes`。

---

本文档与 `AGENTS.md` 互为补足。`AGENTS.md` 是给 AI agent 看的(信任模型、守护层)；本文档是给作者本人看的(具体动手操作时的参考)。两者同时保持同步。
