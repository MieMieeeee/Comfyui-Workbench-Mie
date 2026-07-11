# 实施计划

> 把"循环 SCAIL-2 workflow"包成 Gradio Web UI。
> 原则：每一步都能跑通，每一步都有可验收的产出。

## 阶段 0 — 探活、契约、模板落地（半天）

**目标**：把"开发环境能跑、换机也能跑"的所有前置工作做完。workflow 模板进 repo，路径/端口/阈值进 config，client 封装好，validator 就位。

**任务**：

- [ ] 0.0 写 `app/config.py` — 集中所有路径/端口/阈值（**已落地**）
  - `COMFY_BASE_URL`、`COMFY_INSTALL_DIR`、`COMFY_INPUT_DIR`、`COMFY_OUTPUT_DIR`
  - `PRESETS_DIR`、`RUNS_DIR`、`PARAMS_FILE`
  - `MAX_IMAGE_MB`、`MAX_VIDEO_MB`、`MAX_PROMPT_CHARS`、`ALLOWED_*_EXT`
  - `DEFAULT_TIMEOUT_SEC`、`POLL_INTERVAL_SEC`
  - `GRADIO_HOST`、`GRADIO_PORT`
  - **所有值都接受同名环境变量覆盖**（`COMFY_BASE_URL=... python app.py`）
  - 改路径 → 改这里，不要散落到代码

- [ ] 0.1 写 `app/scail2_client.py`，封装 8 个方法：
  - `load_workflow_template(preset_name)` — 从 `app/presets/{name}.json` 加载（不依赖外部路径）
  - `patch_workflow(workflow, replacements)` — 按 `params.json` 替换 inputs 字段（**不写死节点 ID**）
  - `validate_workflow(workflow, preset_config)` — 加载 + patch 完都跑一遍
  - `upload(file_path, kind)` — 调 `POST /upload/image` 或 `POST /upload/file`
  - `queue_prompt(workflow_json, client_id=None)` — 调 `POST /prompt`，自动包成 `{prompt: ..., client_id: ...}`
  - `get_history(prompt_id)` — 调 `GET /history/{id}`
  - `extract_primary_video_output(history)` — 从 outputs 抓 videos/gifs 第一项
  - `get_output_url(filename, subfolder)` — 拼 `GET /view?filename=...&type=output&subfolder=...`
  - `wait_for_completion(prompt_id, timeout=None)` — generator，yield 状态字符串给 Gradio 流式

- [ ] 0.2 workflow 模板落地（**一次性，复制完就不再依赖外部路径**，**已落地**）：
  - `wan21_scail2_loop_tutorial_final.json` → `app/presets/sca12_uncached.json`（64 顶层键，无 cache，阶段 1 用）
  - `scail2_loop_cached_final.json` → `app/presets/sca12_cached.json`（96 顶层键，带 StringFormat + LoadOrCompute，阶段 2+ 用）
  - 写 `app/presets/params.json`，按 preset 分 key 存 user_facing_inputs + do_not_modify_warnings（**已落地**）
  - **关键差异**：cache 版 `VHS_LoadVideo` 在 node **469**（不是 369），uncached 版在 369；cache 版没有 `ColorTransfer` (503)；cache 版多了 `LoadOrCompute` (512/513) + `ImageHash` (514/515)。`params.json` 已经按 preset 分映射，**不要在 client.py 里写死 369**

- [ ] 0.3 写 `app/workflow_validator.py`（小工具）— **review 强调的关键防御层**：
  - `validate(workflow, preset_config)` — 加载后立即跑一遍
  - 校验 `params.json` 的 4 个 user_facing 节点都存在（`30` + `369/469` + `360` + `479`）
  - 校验 4 个字段（`image` / `video` / `text` / `int_range_end`）都在对应节点的 `inputs` 里
  - 校验至少一个 node 的 `class_type` 是 `VHS_VideoCombine` / `SaveGIF` / `SaveWEBM`（会产出 videos/gifs）
  - 启动 app 时和 smoke test 时各跑一次，失败立即 raise，**不要沉默**

- [ ] 0.4 写 `tests/integration_smoke_client.py`（**集成 smoke**）— 独立测试 client：
  - 上传 `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\input\halfbody.png`
  - 用 repo 内的 `sca12_uncached.json` 入队
  - 入队**前**先跑 `validate()` 一次
  - 轮询 `/history/{id}`，确认 `status.completed == true`
  - 抓 outputs 里的 mp4/gif，验证 `/view` 能下载
  - 用一个驱动视频（任意小 mp4），目标只是确认契约通，不要求完美生成

- [ ] 0.5 写 `tests/curl_smoke.js`（node 兜底）— 验证 API 在浏览器外能用：
  - `curl POST /upload/image` + `POST /prompt` + `GET /history/{id}`，回吐状态

**验收**：`python tests/integration_smoke_client.py` 能看到 sca12_uncached 跑完一帧输出（不要求画面好看，重点是契约通 + validator 不报错）

**踩坑预案**：
- ComfyUI 8188 端口占用 → `Get-NetTCPConnection -LocalPort 8188` 看 OwningProcess
- `LoadImage` 上传完文件名对不上 → 用 `/upload/image` 拿 `name` 字段，不要用 `original_name`
- validator 报"missing node 369"——**别慌**，先 `Get-Content app/presets/params.json` 看 `user_facing_inputs` 里这个 preset 是不是该用 469
- workflow JSON 顶层就是 node ID（API 格式），不是包在 `prompt` 里；`/prompt` 入队时 client 自动包 `{prompt: ..., client_id: ...}`

---

## 阶段 1 — 最小 Gradio 骨架（1 天）

**目标**：跑通 SCAIL-2 loop workflow 的"上传 → 校验 → 入队 → 轮询 → 出视频"端到端。

**任务**：

- [ ] 1.1 写 `app/scail2_app.py` 200 行 Gradio：
  - 表单：3 个 input（参考图 / 驱动视频 / 提示词）+ 1 个 slider（循环段数，默认 8，范围 1-12）
  - 1 个 button（运行）
  - 输出：1 个 `gr.Video`（生成结果）+ 1 个 `gr.Textbox`（状态/进度）

- [ ] 1.2 表单 schema 从 `app/presets/params.json` 自动生成，**不要硬编码 4 个字段**：
  - 当前阶段只读 `presets.sca12_uncached.user_facing_inputs`
  - 字段的 `label` / `min` / `max` / `default` 全部从 JSON 读
  - 这样阶段 2 切 cache 版时，UI 不需要改代码

- [ ] 1.3 输入校验（**前移到 Phase 1**，不要等 Phase 4）— review 建议：
  - 参考图：非空、扩展名 ∈ `{png, jpg, jpeg, webp}`、size ≤ 5MB
  - 驱动视频：非空、扩展名 ∈ `{mp4, mov, webm}`、size ≤ 200MB
  - 提示词：非空、长度 ≤ 2000 字符（允许空 → 给默认值 `"A person walking naturally."`）
  - 校验失败 → `gr.Warning` 显示具体原因 + 阻止入队，**不**返回 generic error
  - 阈值从 `config.MAX_*` 读

- [ ] 1.4 替换 workflow：调 `client.patch_workflow(workflow, {image, video, text, int_range_end})`，replacements 来自表单值。**4 处替换**（原 PLAN 标题"3 处"是笔误，下面实际列了 4 处，已修）：
  - `30.image` ← 参考图文件名
  - `369.video`（uncached）/ `469.video`（cached）← 驱动视频文件名
  - `360.text` ← 提示词
  - `479.int_range_end` ← 段数

- [ ] 1.5 进度反馈：每 2 秒调一次 `get_history()`，用 `gr.Progress` 或 `yield` 流式更新
  - **MVP 不保证百分比进度** — 只显示：elapsed time / `status_str` / 最近执行节点
  - 优先级：`completed/success/failure` > 最近节点 > elapsed time
  - 30 分钟无响应 → `client.wait_for_completion` 自动 timeout，UI 显示 "⏰ timeout after 30min"

- [ ] 1.6 输出视频：从 `extract_primary_video_output(history)` 抓第一项，组装 `/view` URL 喂给 `gr.Video`，**不**先下到本地

**验收**：
- 浏览器开 `http://localhost:7860`，上传一张参考图 + 一段驱动视频 + 填提示词 + 段数=2，按运行。**10 分钟内**看到生成的视频在 `gr.Video` 里能播
- 故意给一个不存在的驱动视频，UI 显示 "drive video not found: xxx.mp4"（具体报错，不是 generic error）
- 故意给一个 300MB 的视频，UI 显示 "Drive video too large (max 200MB)"
- 故意给一个 5MB 以上的图，UI 显示 "Reference image too large (max 5MB)"
- 故意给空提示词，UI 自动填默认值

**踩坑预案**：
- 上传大文件慢 → `gr.File` 替 `gr.Video`/`gr.Image` 减少前端解码；后端用 `requests` 流式上传
- `int_range_end` 改完不生效 → 检查 `MieLoopStart` widget 的值是不是 `widgets_values[1]`，不是 `inputs.int_range_end`（API vs UI 格式差异）
- ComfyUI 跑超时 → 轮询间隔从 2s 拉到 5s；超时上限走 `config.DEFAULT_TIMEOUT_SEC`
- workflow JSON 是 API 格式（node ID 当 key）还是 UI 格式（数组）→ 我们的是 API 格式，直接用
- 提示词里有反斜杠/引号 → 提示词是直接 JSON 序列化的，不要在 client 端做字符串处理

---

## 阶段 2 — cache 版切换（半天）

> **2026-07-10 状态**：🚫 **已放弃**。`sca12_cached.json` 已从仓库移除。
> 详见 `docs/DECISIONS.md` 决策 2 的修订说明。下面内容保留为历史计划档案。

**目标**：切到 `sca12_cached.json`，同输入第二次起秒级命中。

**任务**：

- [ ] 2.1 加一个 `gr.Radio`（uncached / cached，默认 cached）让用户选 preset
- [ ] 2.2 UI 切 preset 时，`scail2_app.py` 从 `params.presets[preset_name]` 读 user_facing_inputs 重新渲染表单。**代码层零改动**，只换数据源
- [ ] 2.3 cached 版的 4 处替换节点 ID 跟 uncached **不完全一样**（VHS_LoadVideo 从 369 变 469）— 但因为 schema 来自 `params.json`，所以 client 层一行不动
- [ ] 2.4 `client.patch_workflow` 写完后，**调用 `validate_workflow` 一次**，确认替换后的 4 个 inputs 字段都非空
- [ ] 2.5 加运行结果展示：是否命中 cache、跑了多久
  - **cache hit 判定依据**（review 强调要写明）：
    - 优先从 `history.status.messages` 找关键字 `"SAM3 execution skipped"` 或 `"cached"` / `"load_or_compute"`
    - 若 API 没明确标记，则用 heuristic：某 `LoadOrCompute` 节点（512 或 513）的 `cache_status` 输出字段是 `hit` / `miss` / `compute` 之一
    - 两者都无 → 视为 miss，在 UI 标注 "cache status: unknown (time-based)"
  - 阶段 1 的 uncached 版没有 cache 链路，固定显示 "cache: n/a"

**验收**：
- 第一次用 cached 跑完 8 段：~660s
- 第二次用完全相同的输入再跑：< 60s（cache HIT），UI 显示 "✅ cache hit"
- 切回 uncached 用同输入跑：~660s（无 cache 行为）
- 故意改一下 prompt 文本，cached 版应该 cache miss（cache key 包含 prompt）

---

## 阶段 3 — run manifest + 历史 Tab（半天）

**目标**：用户能看到自己跑过的所有结果，元数据完整。

**任务**：

- [ ] 3.0 设计 run manifest（**关键，先做这个**）— review 强调的设计与数据源一致问题：
  - 每次运行结束（不管 success / failure / timeout），在 `app/data/runs/{prompt_id}.json` 写一份 sidecar：

    ```json
    {
      "prompt_id": "abc-123-def-456",
      "created_at": "2026-07-08T14:23:05",
      "finished_at": "2026-07-08T14:24:06",
      "duration_sec": 61,
      "preset": "sca12_cached",
      "reference_image": "halfbody.png",
      "drive_video": "demo.mp4",
      "prompt_text": "A person walking naturally.",
      "segments": 8,
      "status": "success",
      "cache_hit": true,
      "output": {
        "filename": "scail-2-loop_00001.mp4",
        "subfolder": "SCAIL-2",
        "type": "output"
      },
      "error": null
    }
    ```
  - 写 manifest 的逻辑在 `scail2_app.py` 的 `run()` 函数里，状态码、cache_hit、输出文件都从 `client` 拿到后填入
  - 历史页**只读 manifest**，**不**直接扫 ComfyUI output 目录（避免元数据缺失）

- [ ] 3.1 写 `app/history.py`：
  - `list_runs()` — 扫 `app/data/runs/*.json` 按 `created_at` 倒排
  - `get_run(prompt_id)` — 读单个 manifest
  - `make_view_url(filename, subfolder)` — 用 `config.COMFY_BASE_URL` 拼 `/view?filename=...&type=output&subfolder=...`

- [ ] 3.2 加一个 `gr.Tabs`："运行 / 历史 / 设置"

- [ ] 3.3 历史 tab 用 `gr.Gallery`（视频缩略图——用 `/view` URL 当 src）+ 右侧 detail panel：
  - 提示词 / 段数 / preset / cache_hit / duration_sec / 创建时间
  - 失败的任务标红 + 显示 `error` 字段

- [ ] 3.4 加"下载"按钮（生成 `/view?filename=...&subfolder=...&type=output` 直链，`<a href>` 标签）

**验收**：
- 跑 3 次不同参数（不同 preset/段数/提示词），刷新页面，历史 tab 显示 3 条记录
- 每条可点开看视频 + 元数据 + 下载
- 跑 1 次故意失败的任务（驱动视频名错），历史里也有一条 record，`status: failure` + `error: ...`

---

## 阶段 4 — 错误处理与 UX 美化（1 天）

**目标**：ComfyUI 端报错用户能看懂；进度不"卡住"感。

**任务**：

- [ ] 4.1 错误分类（review 建议的三类）：
  - **前置校验错误**（`ValidationError`）：文件过大 / 缺少输入 / workflow 缺节点
    - UI: `gr.Warning` 弹具体原因
  - **连接/协议错误**（`ConnectionError` / `ProtocolError`）：8188 连不上 / `/prompt` 非 200 / JSON 解析失败
    - UI: 提示 "ComfyUI at :8188 not reachable, check 启动器"
  - **ComfyUI 执行错误**（`ExecutionError`）：CUDA OOM / 模型缺失 / 节点执行失败
    - UI: 从 `status.messages` 抽关键错误，显示 "❌ ComfyUI: <error message>"
- [ ] 4.2 把 `client.wait_for_completion` 的状态消息统一格式：`(状态) (elapsed) (last_node)`，三段固定
- [ ] 4.3 主题：先 `gr.themes.Soft()`，观察用户反馈
- [ ] 4.4 加"清空输入"和"加载上次的参数"按钮（"上次"从 `RUNS_DIR` 拿最近一次 manifest）
- [ ] 4.5 manifest 里加 `error` 字段的类型化提取（从 `status.messages` 数组找 `execution_error` 节点）

**验收**：
- 故意给一个不存在的驱动视频名：UI 显示 "drive video not found: xxx.mp4"（已在前置校验阶段拦截，**不**到 ComfyUI 端）
- 故意关掉 ComfyUI 再运行：UI 显示 "Cannot connect to ComfyUI at :8188"
- 跑长任务时进度条平滑（每 2-3 秒跳一次，不死锁）

---

## 阶段 5+ — 视情况决定

观察 1-2 周后按真实痛点决定：

| 触发 | 行动 |
|---|---|
| 用户嫌 UI 丑、要品牌色 | 迁 HTMX + FastAPI |
| 要登录、计费、协作 | 迁 Vue 3 + FastAPI |
| 要更多 workflow | 加 preset（sca12 single / source match / post_ct 等），`params.json` 加 key 即可，**代码层零改动** |
| 要"多用户同时跑" | Gradio `queue(max_size=4)` + 反向代理 |

---

## 阶段 6 — 多工作流架构 + 文生图 + TDD 加固（已完成）

**日期**：2026-07-08

在原始 0-4 阶段基础上扩展，全程 **TDD**（每个改动先写失败测试 → 实现 → 测试转绿）。最终 79 个测试全绿。

**子任务**：

- [x] **6.0 修 review 指出的问题 + TDD 加固**
  - `requirements.txt` + `.gitignore`
  - 修 `patch_workflow` 浅拷贝污染 bug（TDD 暴露的真 bug：`dict(v)` 不够，`node["inputs"]` 还是引用）
  - 修 `_max_idx` 重复 append（复制粘贴 bug）
  - `_update_est` 改 kwargs 消除位置耦合
  - 删 `wait_for_completion` 的 `yielded_done` dead code
  - `upload()` 的 `kind` 死参数清理
  - `scail2_app.py` 全文 `\uXXXX` escape 还原为 UTF-8 中文
  - 给 validator / patch_workflow / wait_for_completion / upload 补纯逻辑 unit test

- [x] **6.1 多工作流注册表**
  - `params.json` 每个 preset 加 `display_name` / `category` / `order`
  - `config.list_workflows()` 按 order 排序返回列表
  - UI 改左侧 `gr.Radio` + 右侧 `@gr.render` 动态表单
  - `run_workflow(preset_name, ...)` 首参化

- [x] **6.2 文生图工作流（Z-Image-Turbo）**
  - `zimage.json`（9 节点，从 FollowThisImage `zzz.json` 移植，node-id 化）
  - `params.json` 加 `zimage` preset（prompt_pool + image_sizes + seed）
  - 新增 input type：`prompt_pool`（Textbox + 随机按钮）/ `image_sizes`（CheckboxGroup）
  - `extract_primary_image_output` + `extract_all_image_outputs`
  - `run_image_workflow` 生成器（多尺寸循环 + seed 随机化）
  - validator 扩展接受 image 输出节点（`SaveImage`/`PreviewImage`）+ 复合 type 跳过字段检查

- [x] **6.3 提示词池**
  - 从 FollowThisImage `history/history.json`（5049 条）按类别+长度抽样 22 条 → `app/presets/prompts.json`
  - `app/prompts.py`（`load_pool` / `random_prompt` / `random_prompts`）
  - UI "🎲 随机提示词" 按钮接线

**验收**（全部通过）：
- `python -m pytest tests/ -v` → 79 passed
- `build_ui()` 构造成功，左侧 3 个工作流（SCAIL-2 / SCAIL-2 缓存 / 文生图）
- 22 条提示词，10 个类别，随机抽取正常
- 历史 manifest 读写 round-trip 正常

**没做（明确边界）**：
- FollowThisImage 的 image→VLM→prompt 反推（用户排除）
- cached 版文生图
- 文生图独立历史/画廊页（复用现有历史页，manifest 已含 preset 字段）

---

## 关键参考文件

- t28 笔记（cache 链路原理）: `E:\cc\data\scail2\notes\t28_stringformat_simplified_workflow.md`
- t25 笔记（cache 架构终态）: `E:\cc\data\scail2\notes\t25_final_cache_state.md`
- t12 笔记（ComfyUI 内置 SCAIL-2 节点）: `E:\cc\data\scail2\notes\t12_plugin_node_survey.md`
- ComfyUI HTTP API: `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\script_examples\basic_api_example.py`
- ComfyUI WS API: `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\script_examples\websockets_api_example.py`
- **新增（事实来源）**：repo 内 `app/presets/params.json`、`app/config.py`

## 实施节奏

| 阶段 | 估时 | 累计 |
|---|---|---|
| 0 探活 + 模板落地 + config | 半天 | 0.5 天 |
| 1 Gradio 骨架 + 校验 | 1 天 | 1.5 天 |
| 2 cache 切换 | 半天 | 2 天 |
| 3 manifest + 历史 | 半天 | 2.5 天 |
| 4 错误 + 美化 | 1 天 | 3.5 天 |
| 5+ 视情况 | — | — |

总估：**3.5 天出可用 MVP**，之后看用户反馈迭代。