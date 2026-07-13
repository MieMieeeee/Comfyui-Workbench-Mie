# ADDING_WORKFLOWS.md — 新增工作流程

> 伴随 `AGENTS.md` 的信任模型。内置 workflow = 已知能跑。本文档是作者本人下次要加新工作流时的参考清单。
> UI 上长成什么样 (左侧 emoji 前缀 / 按钮配色 / 状态前缀 / CSS class) 不在本节，在 [`docs/UI_STYLE.md`](./UI_STYLE.md)。

---

## TL;DR

加一个 workflow 的完整流程 = **用户提供 4 样东西** + **作者填 3 个数据文件** + **跑一次生成 preview**：

| 阶段 | 谁 | 做什么 | 输出 |
|---|---|---|---|
| 1 | 用户 | 在 ComfyUI 跑通 → 导出 API 格式 → 告诉作者节点分类 | `xxx.json` + 一段节点说明 |
| 2 | 作者 | 把 workflow JSON 复制到 `app/presets/xxx.json` | 项目里的 workflow 文件 |
| 3 | 作者 | 在 `app/presets/params.json` 加 preset 字段 (含 example 用的文件路径) | preset 配置 |
| 4 | 作者 (程序辅助) | 用 example 参数跑一次 → ComfyUI 出图 → 复制到 `app/static/examples/xxx_xxx.png` | preview 资产 |
| 5 | 作者 | 把 preview 路径写进 params.json example.preview_image / preview_video | example 配齐 |
| 6 | 作者 (可选) | 引入新模型 / 节点 → 追加 `app/presets/health_requirements.json` | 健康检查配置 |
| 7 | 作者 | `python -m pytest tests/ -q` 全绿 + 手动打开 WebUI 看一眼 | 验证 |

**不动代码**。 加新 type 时才动 `_build_input_component`，但 99% 的工作流复用现有 type 即可。

---

## 谁提供什么 —— 拆清楚责任

**用户** (跑工作流的人) 提供：

1. **workflow JSON** —— 在 ComfyUI 调通后，导出为 **API 格式**，原样给作者。不要 Save (format=png) 那个导出版本，那个含图像 base64，体积巨大。
2. **节点分类清单** —— 一段话，列清楚：
   - 哪些节点是 **basic 输入** (默认展开给用户改的字段)
   - 哪些节点是 **advanced 输入** (默认折叠进 🔧 高级参数面板)
   - 哪些节点是 **输出节点** (决定 output_kind；目前支持 image / video)
   - 哪些节点需要 **fixed patch** (preset 写死的值，用户不动)
   - **典型输入示例** —— 用哪张图、哪段视频、什么提示词跑出来的效果最具代表性

**作者** (本仓库维护者) 做：

- 把 workflow JSON 落到 `app/presets/`
- 在 params.json 加 preset 配置
- 跑一次示例生成 preview 资产
- (可选) 更新 health_requirements.json
- 跑测试 + 手动验证

**程序**自动做 (不用手动)：

- 根据 params.json schema 自动生成表单 UI (basic / advanced 分层)
- 自动从 `config.COMFY_INPUT_DIR` 找 example 引用的文件 → stage 到 `.examples_cache/` → 喂给 gr.File
- 自动从 ComfyUI history.outputs 里抓 image / video 输出 (按 node_id 顺序) → 渲染到 output_box
- 自动把 preset 加载到"运行" tab、显示在左侧导航

---

## 步骤 1 — 准备 workflow 模板

从 ComfyUI 导出 API 格式 workflow JSON，**原样复制**到 `app/presets/{name}.json`。

- **命名**: 小写 + 下划线，比如 `t2v_anime_v2.json`、`controlnet_qr.json`
- **不动** workflow 本体 (节点 ID 是真实索引，ComfyUI 导出是对的)
- 一份 workflow JSON 可被多 preset 共享 —— 这些 preset 都用 `workflow_file` 字段指回同一份 JSON。参考：`sca12_replace` / `sca12_motion` 共用 `scail2_motion_transfer_final.json`，只 patch node 353 切换 mode。

---

## 步骤 2 — 用户给的节点分类 → 翻译成 params.json 字段

用户给的"节点清单"翻译成 schema 的映射表：

| 用户说的 | params.json 字段 | 例子 |
|---|---|---|
| "节点 30 是参考图上传 (LoadImage)" | `user_facing_inputs` 里 `{node_id: "30", field: "image", type: "file:image", tier: "basic", label: "参考图"}` | sca12_motion |
| "节点 367 是段长度 (PrimitiveInt)" | `user_facing_inputs` 里 `{node_id: "367", type: "int", tier: "advanced", min: 1, max: 100, default: 81}` | sca12_motion |
| "节点 360 是正向提示词" | `user_facing_inputs` 里 `{node_id: "360", type: "prompt_pool", tier: "advanced", default: "..."}` | sca12_motion |
| "节点 456 是 VHS_VideoCombine 输出" | `output_kind: "video"` (无需 user_facing_input) | sca12_motion |
| "节点 7 是 SaveImage 输出" | `output_kind: "image"` (无需 user_facing_input) | zimage |
| "节点 479 是 max_segments (高级)" | `user_facing_inputs` 里 `{node_id: "479", type: "int", tier: "advanced", ...}` | sca12_motion |
| "节点 353 是 mode 切换 (boolean)" | `fixed_patches: {353: {value: true}}` (作者写死，用户不动) | sca12_motion / sca12_replace 区别 |

字段全集见下节。

---

## 步骤 3 — params.json 里加 preset 的完整 schema

在 `app/presets/params.json` 的 `presets` 字典里加一个新 key。

```jsonc
{
  "<your_preset_name>": {
    // --- 元信息 ---
    "display_name": "中文显示名（用户视角，不要泄露 node_id）",
    "category": "video | image | other",
    "order": 30,                          // 越小越靠前，已有 10 / 20 / 30
    "description": "一句话介绍，用户视角",

    // --- workflow 文件 ---
    "workflow_file": "<your_preset_name>.json",

    // --- preset 级固定 patch（用户不动，作者写死）---
    "fixed_patches": {
      "<node_id>": { "<field>": <value> }
    },

    // --- 暴露给用户的输入 ---
    "user_facing_inputs": [
      {
        "node_id": "<node_id>",
        "field": "<input_field>",
        "label": "中文标签",
        "type": "file:image | file:video | text | prompt_pool | int | bool | image_sizes | int_random",
        "tier": "basic | advanced",
        "default": "...",
        "help": "...",                     // 可选，悬浮提示
        "min": 1, "max": 100, "step": 1,   // int 用
        "also_patch": [...],               // 可选，1 视频绑多 node 用
        "also_patch_reason": "..."         // 可选，给未来维护者看
      }
    ],

    // --- 输出类型，决定 UI 怎么渲染结果 ---
    // 选 image  -> 文本生图 (SaveImage 输出)
    // 选 video  -> 视频生成 (VHS_VideoCombine 输出)
    // 省略      -> 程序按节点 class_type 自动判定 (兼容旧 preset)
    "output_kind": "image | video",

    // --- 运行时 example：用户打开工作流第一眼看到的 ---
    // 详见 §4 跑一次示例生成 preview
    "example": {
      "reference_image": "<文件名.png>",     // file:image 自动解析
      "drive_video":    "<文件名.mp4>",      // file:video 自动解析
      "ref_prompt":     "human",             // node 362 的 text
      "drive_prompt":   "human",             // node 348 的 text
      "main_prompt":    "...",                // node 360 的 text
      "segments":       3,                   // node 479 的 int
      "prompt":         "...",                // prompt_pool 的 text
      "sizes":          ["720x1280"],         // image_sizes 多选
      "seed":           900259427766747,    // int_random 固定值 (给具体值时不勾随机)
      "preview_image":  "app/static/examples/<preset>_<slug>.png",   // output_box 初始显示
      "preview_video":  "app/static/examples/<preset>_<slug>.mp4",   // 视频类 preset 必填
      "contract_sha256": "<参数 + 输入素材 + 预览素材的 SHA-256>"       // 跑完示例后签名
    },

    // --- 给未来维护者的备忘，不是用户配置 ---
    "do_not_modify_warnings": [
      { "node_id": "503", "reason": "段间色阶校色" }
    ]
  }
}
```

### 3.1 `type` 怎么选 —— 从 class_type + field 推断

`type` 不需要你手查文档。下面是 `_build_input_component` 当前支持的全集：

| 节点 class_type | field | type | UI 呈现 |
| --- | --- | --- | --- |
| `LoadImage` | `image` | `file:image` | 上传 + 缩略图 |
| `VHS_LoadVideo` / `LoadVideo` | `video` | `file:video` | 上传 + 视频预览 |
| `CLIPTextEncode` / `PrimitiveString` | `text` | `text` | 文本框 |
| 任何**主**提示词的 `CLIPTextEncode.text` | `text` | `prompt_pool` | 文本框 + "🎲 随机提示词" 按钮 |
| `PrimitiveInt` / int slider / `int_range_end` | `value` | `int` | 滑块 (min/max/step) |
| `PrimitiveBoolean` | `value` | `bool` | 复选框 |
| 任何**带"随机种子"含义**的 int 字段 | `value` | `int_random` | "勾选随机" + 数值 |
| `EmptySD3LatentImage` / `EmptyLatentImage` | `width` / `height` | `image_sizes` | 多选预设尺寸 |
| `MieLoopParamGetInt|Mie` / `*GetFloat|Mie` | `value` | `int` | 滑块 |

**输出节点不需要 user_facing_input**（例如 `SaveImage`、`VHS_VideoCombine`、`PreviewImage`）。它们的 role 通过 `output_kind` 体现。

推断不出来 → 先在 `_build_input_component` 里加这个 type，再在 params.json 用。**不要**加"半工作"的 type 后留下走不到的分支。

### 3.2 `tier` 怎么选 —— basic vs advanced

判断口诀：**90% 用户用默认值就不动** 的字段 → `advanced`。

- `basic` —— 默认显示在主区域，用户每次都要改的字段
- `advanced` —— 折叠进 🔧 高级参数面板，用户偶尔才碰

参考 SCAIL-2：主提示词 `basic`，ref_prompt / drive_prompt / frames_per_segment / pre_drop / max_segments 都是 `advanced`。

### 3.3 `output_kind` 怎么选 —— 决定 output_box 怎么渲染

- `"image"` → output_box 渲染 `<img>` 网格（多尺寸时多张图）
- `"video"` → output_box 渲染 `<video controls>` + 输出文件名 caption
- 省略 → 程序按"outputs 里第一个 video/gif"还是"images"自动判定

**怎么知道该填 image 还是 video**：

1. 看 workflow 的输出节点 class_type：
   - `SaveImage` / `PreviewImage` (且下游是 image) → `"image"`
   - `VHS_VideoCombine` / `VHS_SaveVideo` → `"video"`
2. 看用户在节点清单里"哪些是输出节点"那一行。如果用户说"VHS_VideoCombine 是输出"，就是 video。

### 3.4 `also_patch` —— 1 份视频绑多个 node

典型场景：SCAIL2 的 `node 369` (Drive Slice, 按段切驱动视频) 和 `node 469` (Full Source, 取整段视频的音频 + 元信息) **必须绑同一份视频**。否则音频丢失 / 帧数不匹配 / `MieLoopEnd` 报 `Start index is out of range`。

**这是 schema 层 (不是新代码) 的解决方案**：在 `file:video` 项上挂 `also_patch`，运行时会自动把同一份 `drive_name` 写到列表里的每个 node。

格式：

```jsonc
{
  "node_id": "369",
  "field": "video",
  "label": "驱动视频",
  "type": "file:video",
  "tier": "basic",
  "also_patch": [{"node_id": "469", "field": "video"}],
  "also_patch_reason": "node 469 取音频 + 元信息，必须和 node 369 用同一份"
}
```

- `also_patch` 可选；缺省 / `[]` 退化为只 patch 主 node（旧 preset 兼容）
- 每项形如 `{"node_id": "...", "field": "..."}`；同一份 `drive_name` 写到 `replacements[enid][efield]`
- 主 node id 又出现在 `also_patch` 不会丢主字段（覆盖写同名，值相同）
- `workflow_validator` **不**校验 `also_patch` 列出的 node 是否存在（运行时 `patch_workflow` 隐式覆盖 inputs 来保证）
- `also_patch_reason` 是给未来维护者看的备忘，不是运行时逻辑

什么时候**不**需要 `also_patch`：

- 只有 1 个 node 拿这份视频 → 不需要
- 多个 node 但拿不同视频 → 每个 node 各自开一个 `file:video` 项，不要用 `also_patch`
- patch 一个非视频字段 → 用 `fixed_patches` (preset 级)，不是 `also_patch` (user_facing 级)

### 3.5 `fixed_patches` —— preset 级写死

Preset 自带的固定 patch，入队前**先**应用。适用场景：

- 同一份 workflow JSON 被多 preset 复用（例：`sca12_replace` / `sca12_motion` 共享 `scail2_motion_transfer_final.json`，仅 patch node 353 切换 mode）
- preset 想覆盖 workflow 里的某个默认值，但不想让用户每次都改

格式跟 `user_facing_inputs` 的 `replacements` 一致。

### 3.6 `do_not_modify_warnings` —— 备忘录，不是配置

给接手者看的备忘，不是用户配置。主要起到提醒"这个节点动之前先想明白"。

---

## 步骤 4 — 跑一次示例生成 preview

【**项目规矩**】每个 preset 的 `example` 是它的**默认参数** + **典型运行结果**，用户打开工作流后第一眼看到的就是 example 跑出来的图/视频（塞进 output_box 的 `<img>` / `<video>`）。这条规矩适用于：

- 现有 preset：`zimage` (文生图) / `sca12_motion` (动作迁移) / `sca12_replace` (角色替换)
- 未来新加的所有 preset

example 字段拆成两半：

| 字段 | 含义 | 怎么准备 |
|---|---|---|
| **input 部分** | 表单默认值（reference_image / drive_video / prompt / seed / ...） | 作者把文件放进 `config.COMFY_INPUT_DIR`、在 params.json 里写文件名 |
| **preview 部分** | 跑完的实际产物（preview_image / preview_video） | **用 example 参数跑一次 workflow** → 把输出复制到 `app/static/examples/` |

### 4.1 准备 example 输入文件

把要喂给 example 的文件（参考图、驱动视频）放到 `config.COMFY_INPUT_DIR`（默认 `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\input`）。命名建议：

```
<preset_slug>_<descriptor>.<ext>
例：sca12_motion_ref.png / sca12_motion_drive.mp4
例：zimage_ref_<size>_<counter>.png
```

### 4.2 写 example 的 input 字段

params.json 的 `example` 块里只填**文件名**（不带路径），`_resolve_example_file` 会自动从 `COMFY_INPUT_DIR` 找并 stage 到 `.examples_cache/`：

```jsonc
"example": {
  "reference_image": "sca12_motion_ref.png",   // 自动从 COMFY_INPUT_DIR 找
  "drive_video":    "sca12_motion_drive.mp4",
  "ref_prompt":     "human",
  "drive_prompt":   "human",
  "main_prompt":    "a person dancing gracefully in the garden",
  "frame_load_cap": 100,
  "segments":       3
  // 暂时不填 preview_image / preview_video，下一步跑出来再填
}
```

### 4.3 用 example 参数跑一次

两种方式（任选）：

**方式 A —— 走 WebUI（推荐，直观）**：

1. `python app/scail2_app.py` 启动 WebUI
2. 浏览器开 `http://127.0.0.1:8199`
3. 左侧选新加的 preset，点"加载示例素材"（表单自动填好）
4. 点"开始运行"，等结果
5. **不要关 WebUI**，下一步还要用

**方式 B —— 走 ComfyUI API（脚本批处理）**：

如果想把"跑一次 → 拉结果"做成脚本循环（批量给多个 preset 生成 preview），调 `app/scail2_client.py` 暴露的 `queue_prompt` + `get_history` + `get_output_url` 三件套：

```python
from app import scail2_client as c
import json

# 1) 跑 prompt
prompt_id = c.queue_prompt("E:\\FF\\ComfyUI_Mie_2026_V8.0\\ComfyUI\\input\\my_workflow_api.json", wait=True)
# 2) 拉 history
history = c.get_history(prompt_id)
# 3) 提取 output
out = c.extract_primary_video_output(history) or c.extract_all_image_outputs(history)[0]
url = c.get_output_url(out)
# 4) 下载到本地
import urllib.request
data = urllib.request.urlopen(url).read()
with open(r"F:\ComfyUIWebToRunWorkflow\app\static\examples\my_preset_0001.png", "wb") as f:
    f.write(data)
```

### 4.4 把结果复制到项目

无论方式 A 还是 B，最终从 ComfyUI 拿到的产物是：

- **图片类**：在 `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\output\` 下的 `xxx_00001.png`
- **视频类**：在 `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\output\<prefix>\` 下的 `xxx_00001.mp4`

把文件复制到项目内：

```bash
# PowerShell 例
Copy-Item "E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\output\my_preset_00001.png" `
          "F:\ComfyUIWebToRunWorkflow\app\static\examples\my_preset_0001.png"
Copy-Item "E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\output\MyPrefix\my_preset_00001-audio.mp4" `
          "F:\ComfyUIWebToRunWorkflow\app\static\examples\my_preset_3seg.mp4"
```

**命名约定**：

| preset 类型 | preview 文件命名 |
|---|---|
| 文生图 (zimage 等) | `{preset}_{size_slug}_{counter}.png`，例 `zimage_720x1280_0001.png` |
| 视频 (sca12 等) | `{preset}_{seg_count}seg.png` + `{preset}_{seg_count}seg.mp4`（同一帧两个格式：png 做 video poster、mp4 做实际播放） |
| 音频 | `{preset}_0001.wav`（预留，目前还没音频类 preset） |

### 4.5 把 preview 路径写进 example

把 §4.4 复制出来的相对路径写进 params.json：

```jsonc
"example": {
  "reference_image": "sca12_motion_ref.png",
  "drive_video":    "sca12_motion_drive.mp4",
  ...
  "preview_image":  "app/static/examples/sca12_motion_3seg.png",
  "preview_video":  "app/static/examples/sca12_motion_3seg.mp4"
}
```

视频类 preset 必须**同时**填 `preview_image` 和 `preview_video`：
- `preview_video` 优先渲染（视频控件）
- `preview_image` 是 video 的 poster / fallback（视频加载失败时显示）

**测试**：保存 params.json 后切到 WebUI 该 preset，右栏"生成结果"应该立刻显示这张图 / 这段视频，**不需要**先点运行。

### 4.6 给 example 参数与素材签名

真实跑完并复制 preview 后，运行：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_preset_must_have_example.py -q -k example_contract_matches
```

新建或更新过的 preset 会显示 `current=<sha256>`。把这个值写进
`example.contract_sha256` 后再重跑，必须转绿。签名覆盖：

- 除 preview/file 路径外的全部 example 默认参数（包括正向提示词、尺寸、seed）
- `reference_image` / `drive_video` 的实际文件字节
- `preview_image` / `preview_video` / `preview_audio` 的实际文件字节

因此只改提示词、只换输入素材或只替换输出 preview，都会让测试失败。必须用新参数
真实跑一次并替换对应 preview，最后才更新签名。

### 4.7 example 字段约束

被 `tests/test_preset_must_have_example.py` 锁住：

- `example` 必须是非空 dict
- 至少覆盖一个 user_facing_inputs 字段（避免 example 是空 dict）
- output_box 初始值必须含 `preview_image` / `preview_video` 之一
- URL 必须是 `/gradio_api/file=` 前缀（Gradio 6 静态文件路由，详见 AGENTS.md "Gotcha" 段）
- 初始表单组件值必须直接等于 `example`，不能依赖浏览器 load/change 事件二次覆盖
- 本地 preview URL 必须带文件内容哈希 `?v=...`，同路径替换素材后浏览器不能命中旧缓存
- `contract_sha256` 必须匹配当前默认参数、输入素材与 preview 的组合签名

---

## 步骤 5 — 引入新模型 / 节点 → 追加 health_requirements.json

只有新 workflow 用了**现有 health_requirements.json 里没有**的模型 / 节点依赖时才需要追加。已有节点复用即可（所有 ComfyUI-MieNodes 节点、常见 loader 都在里面）。

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

---

## 步骤 6 — 验证

三轮检查：

1. `python -m pytest tests/ -q` —— 应全绿。报错意味着 params.json 与 workflow 存在契约漂移，按报错修。
2. `python app/scail2_app.py` —— 启动日志里的 preflight 会打印 preset 状态。三个 preset 都"OK"才算过。
3. 手动：浏览器开 `http://127.0.0.1:8199`：
   - 左侧应出现你加的 workflow（按 `order` 排序）
   - 点"加载示例素材" —— 表单应一键填满
   - **右栏"生成结果"应立刻显示 preview_image / preview_video**（不需要点运行）
   - 点"开始运行" —— 能拿到与 preview 一致的输出（验证 example 跑得通）

### 失败排查顺序（参考 AGENTS.md 信任模型）

1. 用户输入（参数、文件大小、提示词长度）
2. ComfyUI 进程 / 端口状态（到"系统设置" tab 点"完整健康检查"看报告）
3. 资源（VRAM、磁盘、文件大小上限）
4. **最后才怀疑 workflow 本身**

"最后怀疑" = workflow 在你环境能跑通、只是某个表单字段传错了类型在 user_facing_inputs 里。修 params.json，**不动代码**。

---

## 高频模式：一份 workflow 衍生多个 preset

同一份 workflow 想给不同场景用不同默认值，是最高频的加工作场景之一。零代码做法：

- 多个 preset key，全部 `workflow_file` 同一个 JSON
- 仅在 `fixed_patches` 和 `user_facing_inputs` 上不同
- example 文件可以复用，也可以分别准备

例子：

| preset key | workflow_file | fixed_patches | user_facing_inputs |
|---|---|---|---|
| `sca12_motion` | `scail2_motion_transfer_final.json` | `353.value = true` | 8 个输入，主提示词是 advanced |
| `sca12_replace` | `scail2_motion_transfer_final.json` | `353.value = false` | 同上但 input 顺序可以微调 |

要再加一个变体（例如"SCAIL2 高清版"），只加 preset key、`fixed_patches` 改参数、`user_facing_inputs` 加一个 int 控制强度。**代码零变动**。

---

## 加完后会看到什么

- `app/data/runs/` 下出现你这个 preset 的运行 manifest，点"历史记录" tab 可看到
- 如果加了新节点或模型，"完整健康检查"里会出现它们
- Preset 名称出现在左侧"工作流"列表，按 `order` 排序
- "加载示例素材"按钮可用 —— 只要你填了 `example`
- 右栏"生成结果"展示 preview_image / preview_video（默认就有，不需要先点运行）

代码侧 **什么都不会**变。

---

## 几条口诀

- **节点 ID 写错** → `workflow_validator.validate` 会报 "missing node X"。这是契约漂移侦测，**不要**绕过。
- **field 名写错** → 同上，但报错信息是 "missing inputs.X"。
- **示例输入文件不在 ComfyUI input 目录** → "加载示例"按钮不填 file 字段（其它字段仍填），用户手动上传。不是 bug，是 fallback。
- **示例输出没复制到项目** → 右栏 output_box 显示的是默认占位符（"运行后这里显示结果"），用户跑完之后才看到结果。需要按 §4.4 补 preview 资产。
- **同一份 workflow 多 preset 共享** → 用 `workflow_file` 显式指明，别依赖默认。
- **新工作流需新 type** → 走"拓 schema"路径（`_build_input_component` 先加，再用），不要单独写代码。
- **新工作流用了列表里没有的模型 / 节点** → 记得追 `health_requirements.json` 里的 `models` 或 `custom_nodes`。
- **Gradio 6 静态文件路由是 `/gradio_api/file=` 不是 `/file=`** → 见 AGENTS.md "Gotcha" 段，不要在 src 里写 `/file=`。
- **示例参数跑出来的图跟用户想象的不一样** → 调 prompt / seed / 参考图；不是改 schema。

---

本文档与 `AGENTS.md` 互为补足。`AGENTS.md` 是给 AI agent 看的（信任模型、守护层）；本文档是给作者本人看的（具体动手操作时的参考）。两者同时保持同步。
