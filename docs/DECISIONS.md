# 决策记录

> 记录我们做过的关键技术选型。后续接手的人能快速知道"为什么这么选"。

## 决策 1：用 Gradio 而不是 Blueprint 包装

**日期**：2026-07-08
**状态**：✅ 采纳

**背景**：
ComfyUI 0.24 自带 "Blueprint" 机制，可以把复杂 workflow 包成"单节点 + label 化 widget"，已经在 `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\blueprints\` 下有 80+ 现成 blueprint，包括一个 `Character Replacement (SCAIL-2 Base).json`。

**评估过的选项**：

| 选项 | 工作量 | UX 质量 | 用户需懂 ComfyUI？ | 适合场景 |
|---|---|---|---|---|
| Blueprint (ComfyUI 子图节点) | 低 | 中（单节点 + 表单） | 是 | 在 ComfyUI 内使用 |
| Gradio（独立 Web） | 中（~200 行 Python） | 中（默认主题朴素） | 否 | 给非 ComfyUI 用户用 |
| HTMX + FastAPI | 中-高 | 高 | 否 | 产品级（阶段 5+） |
| Vue 3 + FastAPI | 高 | 最高 | 否 | 长期产品（阶段 5+） |

**决定**：
选 **Gradio**。

**理由**：
1. 目标用户明确说"想用 SCAIL-2 但不想用 ComfyUI 界面"。Blueprint 仍然在 ComfyUI 节点编辑器里，不符合这个目标。
2. 你已有 `E:\cc\data\scail2\scripts\queue_*.js` 和 `workflows/run_scail2_*.py` 的 HTTP 调用逻辑可参考，Gradio 客户端 200 行就能复用模式。
3. workflow 60+ 节点中只有 4 处需要每次改（参考图、驱动视频、提示词、循环段数），Gradio 表单完美覆盖。
4. 写 200 行 + 半天就能跑通端到端，比 Vue + Vite 那一套快一个数量级。

**已知妥协**：
- Gradio 默认主题不漂亮，将来可能需要 CSS hack 或升级
- 不适合"多人协作"、"登录"、"计费"——这些需求出现时再升级到 FastAPI + Vue

**参考截图**：
- 现状 79 节点铺满画布: `E:\cc\data\scail2\workflows\wan21_scail2_loop_fixed_canvas_cached_final.json` 加载后的样子
- Blueprint 形态（已验证可工作）: `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\blueprints\Character Replacement (SCAIL-2 Base).json`

---

## 决策 2：第一版用 `tutorial_final.json`，第二版切 cache 版

**日期**：2026-07-08
**状态**：✅ 采纳（阶段 1 vs 阶段 2 的分工）

**背景**：
我们有 2 个 SCAIL-2 循环 workflow：
- `tutorial_final.json`（60 节点，无 cache）—— 简单直接，但同输入每次重跑
- `loop_fixed_canvas_cached_final.json`（79 节点，StringFormat + LoadOrCompute）—— 重复输入秒级命中

t28 笔记确认 cache 版在二次同输入跑时从 660s 降到 60s。

**决定**：
- **阶段 1 用 tutorial_final.json** 跑通端到端逻辑（避免一开始就被 cache key 拼接的正确性绊倒）
- **阶段 2 切到 cache 版**，加 cache hit/miss 提示

**理由**：
1. tutorial_final.json 节点少、链路清晰，调试 ComfyUI HTTP API 交互时不会被 cache 行为干扰
2. cache 版需要在 6 个节点上保证 `StringFormat` template 不被破坏，复用难度大
3. 阶段 2 切换时只要把 JSON 模板换了，client 层一行不动

**回退方案**：
如果 cache 版遇到 bug，可以从 `tutorial_final.json` 临时回退——两者参数替换规则一致（4 个节点位置相同）。

---

## 决策 3：ComfyUI 与 Gradio 分进程，端口分离

**日期**：2026-07-08
**状态**：✅ 采纳

**决定**：
- ComfyUI 跑端口 8188（已存在，不动）
- Gradio 跑端口 7860（新增）
- 两者不共享内存，只通过 HTTP + 磁盘文件交互

**理由**：
- ComfyUI 是 GPU 密集型，Gradio 是 I/O 密集型，分进程不会互相阻塞
- ComfyUI 升级时不影响 Gradio 端代码（只要 API 兼容）
- 调试 ComfyUI 时可以单独重启 Gradio，反之亦然

**通信链路**：
- 用户上传文件 → Gradio `/upload/image|file` → ComfyUI `input/` 目录
- workflow JSON → Gradio `/prompt` → ComfyUI 执行
- 生成视频 → ComfyUI `output/SCAIL-2/` → Gradio 通过 `/view` 拿 URL 直接喂给 `<video>`

---

## 决策 4：上传走 ComfyUI API，不直接写磁盘

**日期**：2026-07-08
**状态**：✅ 采纳

**背景**：
另一个方案是 Gradio 端直接把文件写到 `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\input\`，绕过上传 API。

**决定**：
走 `POST /upload/image` 和 `POST /upload/file` 上传，不用文件系统直写。

**理由**：
1. ComfyUI 端有同名文件处理逻辑（`overwrite=true` 标志），直写可能踩坑
2. 保留未来"远程 ComfyUI 实例"的可能（直写需要共享磁盘）
3. 路径权限问题：直写要 Gradio 进程有写 ComfyUI 目录的权限，跨用户/跨机器时易出问题

**代价**：
多一次 HTTP 请求（~10ms），可忽略。

---

## 决策 5：单段 vs 多段循环，统一通过 `int_range_end` 控制

**日期**：2026-07-08
**状态**：✅ 采纳

**背景**：
循环段数在 `MieLoopStart` 节点（node 479）的 `int_range_end` widget 上。值为 N 表示跑 N 段（每段 81 latent 帧 ≈ 5.4s 视频）。8 段 ≈ 43s 视频。

**决定**：
- 默认 8 段
- 范围 1-12（>12 在 RTX 4090 上容易 OOM，警告用户）
- 视频长度建议 = 段数 × 5.4s 写进 UI 提示

**理由**：
用户场景里"用 SCAIL-2 循环换脸"就是要把短视频变长。1 段几乎没用（==单段），12 段是实测上限（vRAM 17GB）。

**未来扩展**：
如果用户要"长视频 (5 分钟)"，要把 `int_range_end` 配 `LoadOrCompute` 缓存，cache hit 时光跑采样不跑 SAM3，能撑到 20+ 段。

---

## 决策 6：错误处理"先简后繁"

**日期**：2026-07-08
**状态**：✅ 采纳

**决定**：
- 阶段 1：catch 所有 exception，display 一行红字
- 阶段 4：根据 `status.status_str` 和 `status.messages` 数组做精细化错误提示

**理由**：
阶段 1 目标只是"跑通"，错误信息糙没关系。
阶段 4 再花时间打磨——那时候我们已经知道哪些错误最常出现（CUDA OOM / model 缺失 / 输入文件超限）。

---

## 决策 7：不写 unit test，只写 smoke test

**日期**：2026-07-08
**状态**：✅ 采纳

**决定**：
- 不写 pytest unit test
- 只写 `tests/smoke_client.py` 和 `tests/curl_smoke.js` 端到端冒烟
- 阶段 4 加"输入校验"逻辑时再考虑加针对性的单测

**理由**：
1. 这是一个"胶水项目"——`scail2_client.py` 主要是 HTTP 调用包装，没有业务逻辑
2. 端到端 smoke 跑一次 = 验证 client 正确 + ComfyUI 在跑 + workflow JSON 正确
3. 写 unit test 是给"会被多人改的代码"用的，我们这项目就 1-2 个人维护

**回退条件**：
如果某天 `scail2_client.py` 复杂度上升（多 workflow 调度、retry 逻辑、cache key 计算），再补单测。

---

## 决策 8：当前进度产出

**日期**：2026-07-08（最近更新：2026-07-08）

| 阶段 | 状态 |
|---|---|
| 0 探活 + 模板 + config | ✅ 完成 |
| 1 Gradio 骨架 + 校验 | ✅ 完成 |
| 2 cache 切换 | ✅ 完成 |
| 3 历史 tab + manifest | ✅ 完成 |
| 4 错误处理 + 进度 | ✅ 完成 |
| 多工作流架构 | ✅ 完成 |
| 文生图工作流 | ✅ 完成 |

---

## 决策 9：多工作流架构 —— 左侧列表 + schema 驱动动态表单

**日期**：2026-07-08
**状态**：✅ 采纳

**背景**：
原来只支持 SCAIL-2 一个 workflow（`PRESET_NAME` 硬编码）。要支持视频换脸 + 文生图 + 未来更多，需要多工作流。

**评估过的选项**：

| 选项 | 扩展成本 | UX | 实现复杂度 |
|---|---|---|---|
| 顶部 Tab 平铺每个 workflow | 低（加 Tab） | 中（workflow 多了顶部挤） | 低 |
| 左侧列表 + 右侧 `@gr.render` 动态表单 | 极低（加 preset 即可） | 高（插件式） | 中 |
| 卡片选择器首页 | 中 | 最高（产品感） | 高（状态管理复杂） |

**决定**：选**左侧列表 + 右侧 `@gr.render` 动态表单**。

**理由**：
1. 现有 `_build_form` / `_build_input_component` 已是 schema 驱动（从 `params.json` 读），加新 workflow 零代码改动 —— 这是最重要的复用。
2. `params.json` 本来就是多 preset 容器（`presets.{name}`），给它加 `display_name`/`category`/`order` 元数据即可驱动左侧列表。
3. `@gr.render(inputs=[radio])` 在 Gradio 6 是稳定 API，选不同 workflow 时右侧自动重建表单。
4. plugin 式感觉：扩展只动数据（params.json + workflow JSON），不碰代码，符合"胶水项目"的低维护诉求。

**已知妥协**：
- `@gr.render` 每次切换重建组件，组件状态（已填的表单值）会丢失 —— 单机工具可接受。
- 复合 type（如 `image_sizes`）需要运行时专门逻辑（`run_image_workflow` 循环 patch），不能纯靠 schema。

---

## 决策 10：文生图移植 —— 复用本项目 client，不引入 FollowThisImage 的 WS 客户端

**日期**：2026-07-08
**状态**：✅ 采纳

**背景**：
FollowThisImage（`C:\Users\administered\PycharmProjects\FollowThisImage`）有成熟的文生图链路（Z-Image-Turbo），但它的 ComfyUI 客户端用 WebSocket 等待（`comfy_api_simplified/`），本项目用轮询（`wait_for_completion`）。

**决定**：只移植 workflow JSON（`zzz.json` → `zimage.json`）和 UI 设计思路（多尺寸 + 随机种子），**不**移植它的 WS 客户端。

**理由**：
1. 本项目 `scail2_client.wait_for_completion` 轮询方案已稳定、有测试覆盖（5 个测试），文生图复用即可，无需引入 `websockets` 依赖。
2. node 寻址统一用 node id（本项目既有约定），把 FollowThisImage 的 node-title 寻址（`set_node_param("title", ...)`）改成 node-id 寻址（`patch_workflow({"6": {"text": ...}})`），跟视频 workflow 一致。
3. 文生图 workflow 只有 9 节点，结构简单，直接 `json.load` + `patch_workflow` 即可，不需要 FollowThisImage 的 `ComfyWorkflowWrapper` 抽象。

**移植的东西**：
- `zzz.json`（9 节点 Z-Image-Turbo）→ `app/presets/zimage.json`（重置 prompt 为中性默认）
- 多尺寸批量逻辑（`sizes=[(1024,1024),(1280,720),...]` 循环 queue）—— 放进 `run_image_workflow`
- seed 随机化（`seed=0` → 每尺寸 `random.randint(1,10**12)`）

**没移植**：
- FollowThisImage 的 image→VLM→prompt 反推功能（用户明确排除）
- `comfy_api_simplified/` WS 客户端
- 历史/画廊/starred UI

---

## 决策 11：提示词池 —— 从 FollowThisImage history 抽样，非实时反推

**日期**：2026-07-08
**状态**：✅ 采纳

**背景**：
FollowThisImage **没有提示词池** —— 它的 prompt 全由 VLM（Qwen3-VL）从输入图反推生成。用户要"从项目里随机拿提示词"，需要自己建池。

**决定**：
从 FollowThisImage 的 `history/history.json`（5049 条真实生成记录）按类别+长度筛选抽样，生成 `app/presets/prompts.json`（22 条，10 个类别）。

**抽样策略**：
1. 按主题分桶（portrait / landscape / vehicle / interior / nature / food / animal / cityscape / product / portrait-m）
2. 长度过滤 250-600 字符（高质量但不冗长）
3. 每桶去重 + 按配额抽样（portrait 6 条，其他 1-4 条）
4. `random.seed(2026)` 固定，保证可复现

**理由**：
1. 这些是真实跑过的 prompt，质量有保证。
2. 类别覆盖广，避免 FollowThisImage 历史里"woman/portrait"高度集中的问题（4388/5049 都是 woman）。
3. 用户可手动编辑 `prompts.json` 扩充池子；UI 上"🎲 随机提示词"按钮调 `prompts.random_prompt()`。

**未来扩展**：
- 如果要更大池子，可把每次文生图跑完的 prompt 追加进池（需处理去重/上限）。
- 如果要 VLM 反推，可作为第四个 workflow preset（image→prompt→image），复用现有架构。

---

## 决策 12：ComfyUI 地址运行时可变，WebUI 与 ComfyUI 解耦

**日期**：2026-07-08
**状态**：✅ 采纳

**背景**：
原来 ComfyUI 地址是 `config.COMFY_BASE_URL` 模块级常量（从环境变量/默认值来），**启动后不可变**。启动脚本 `start_webui.bat` 还会硬性检查 ComfyUI 是否在 8188 跑、没跑就尝试拉起启动器并阻塞等待 90 秒 —— 这把 WebUI 启动和 ComfyUI 强耦合。

参考 FollowThisImage：它有一个 `⚙️ Settings` accordion，运行时可改 ComfyUI URL（`update_comfy_url` → `comfy.set_url`）。

**决定**：
- `scail2_client` 加运行时可变 base URL（`_runtime_base_url` 模块变量 + `get_base_url` / `set_base_url` / `reset_base_url`）。
- 所有 HTTP 调用（upload / queue_prompt / get_history / get_output_url）+ `history.make_view_url` 都走 `get_base_url()`，不直接读 `config.COMFY_BASE_URL`。
- 加 `check_connection(url=None, timeout)` → `(ok, msg)`，调 `/system_stats`，不抛异常。
- UI 加"⚙️ 设置" tab：URL 输入框 + "保存并测试" + "恢复默认" + "重新测试"。
- `start_webui.bat` 去掉 ComfyUI 检查/启动逻辑，只负责装依赖 + 启 Gradio。

**理由**：
1. **解耦**：WebUI 能独立启动（ComfyUI 没跑也能打开界面配置），ComfyUI 就绪后再去设置页测试连通 —— 比 bat 阻塞等待 90 秒体验好。
2. **多实例**：用户可在 UI 切换不同 ComfyUI 实例（本地 / 局域网 / 远程），无需重启或改环境变量。
3. **可测**：`set_base_url` / `check_connection` 是纯逻辑，10 个 unit test 覆盖（`test_runtime_url.py`）。
4. FollowThisImage 的方案已验证可行，本项目沿用并强化（多了"恢复默认"和"重新测试"）。

**已知妥协**：
- 运行时 URL 存在模块变量里（进程内），重启 WebUI 会丢失 → 但 config 默认值兜底，且用户多半每次都用同一个地址。如果要持久化，可写进一个 `app/data/settings.json`（未做）。
- `set_base_url` 不校验 URL 格式（只 strip + 去尾斜杠），靠 `check_connection` 实测反馈。## 决策 N: 文件命名里的 scail2 是历史包袱，不是新约定 (2026-07-12)

**日期**: 2026-07-12 (清理 commit 时回填)
**状态**: ✅ 记录在案

**背景**:
本项目第一版 (ed2368e) 是 SCAIL-2 专用 wrapper, 后来加 zimage 才变成多工作流. 但**文件从来没改名**, 导致:

- `app/scail2_app.py` (UI 入口) — 全项目 30+ 处 import, 改名代价远大于收益
- `app/scail2_client.py` (ComfyUI HTTP 客户端) — 同上
- `app/presets/sca12_uncached.json` — SCAIL-2 历史工作流, 已被 `scail2_motion_transfer_final.json` 取代
- `app/presets/sca12_cached.json` — 早期 cache 实验稿, 已撤废 (commit 3e89ed1)

**决定**:
- **代码文件名** (`scail2_app.py` / `scail2_client.py`): 保持原名, **不改**. 改名要改 30+ import + 所有 doc 引用, 无功能收益.
- **workflow 模板文件** (`sca12_uncached.json` / `sca12_cached.json`): 已撤废删除. SCAIL-2 preset 都指 `scail2_motion_transfer_final.json`.
- **Preset 名** (`sca12_motion` / `sca12_replace`): 保持, 因为它们在 `params.json` / manifest / 启动日志里都出现, 改名 cascade 太大. display_name 已用中文.

**"uncached" 名字的来由** (详见决策 2):
原版 SCAIL-2 workflow 有两份:
- `tutorial_final.json` / `sca12_uncached.json` — 无 Cache Key 节点, 每次重跑
- `loop_fixed_canvas_cached_final.json` / `sca12_cached.json` — 有 StringFormat + LoadOrCompute + Cache Key 节点, 同输入秒级命中 (660s → 60s)

"cached" / "uncached" 指的是 ComfyUI-MieNodes 的 **Cache Key 节点基础设施**, 不是 ComfyUI 一般执行缓存. 两份 workflow 的 ComfyUI 一般执行缓存都生效.

**未来加新 workflow 的命名规则** (新约定):
- preset key: 下划线分隔小写, 例 `zimage`, `t2v_anime_v2`, `controlnet_qr`
- workflow file: 同 preset key 加 .json 后缀, 或 `<scope>_<variant>.json`
- sca12 前缀仅限 SCAIL-2 系列 preset (历史已用); 其它 preset 不强求前缀
- display_name 用中文用户视角的词, 不要泄露 node_id 或内部命名

**回退 / 改名时机**:
哪天项目从 0 重新组织 (比如改用 FastAPI + Vue, 整个 app/ 目录推翻), 那时候顺便改文件名. 现在改不值.

