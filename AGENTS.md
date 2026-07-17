# AGENTS.md -- ComfyUIWebToRunWorkflow

> Project-level context for Codex / AI agents working on this codebase.
> Main AGENTS.md (C:\Users\administered\.codex\AGENTS.md) covers tooling;
> this file covers project direction.

## Project identity

- The author is the maintainer of a **ComfyUI integration bundle + launcher**.
  This repo is the **companion multi-workflow WebUI** that ships with that launcher.
  It is not a standalone product.
- Built-in workflows (app/presets/*.json) are curated and validated by the author
  himself, with node-IO annotations. They are a **pre-vetted set**, not user-submitted
  third-party workflows.

## Trust model -- this section decides code direction

**Built-in workflows are known to run.**

- Do NOT assume workflows may hit plugin-compat / missing-node issues at runtime.
- app/workflow_validator.py stays as a **config-drift sanity check**
  (catches wrong node_id / field in params.json after a manual edit),
  NOT as a plugin-availability gate. It runs once after patch_workflow; fail = refuse to queue.
- app/health_check.py L2/L3 (models / custom nodes) stays -- but its audience is the
  **user's deployment environment** (which file the user's ComfyUI instance is missing),
  not the workflow's own trustworthiness. When it reports X missing, the message should
  say 'your ComfyUI instance is missing X', not 'workflow requires X, we did not install it'.
- Failure-investigation priority (shapes debug paths):
    1. User input (params, file size / format, prompt length)
    2. ComfyUI process / port status
    3. Resources (VRAM, disk, file-size limit)
    4. **Only last** should the workflow itself be suspected
- When writing new preflight / auto-recovery / fallback branches, do NOT stack defenses
  on the 'plugin might be missing' assumption.

## Workflow-addition path (data-driven, NO new code)

The author will keep providing new workflows. For each, he supplies a short note:
'these nodes are user input / output, here are their field names'.

Adding a workflow means touching ONLY data, in three possible files.
For the full recipe (field reference, validation flow, debug sequence), see
[`docs/ADDING_WORKFLOWS.md`](./docs/ADDING_WORKFLOWS.md).

| File | What to change |
| --- | --- |
| app/presets/{name}.json | the workflow template itself |
| app/presets/params.json | preset config: display_name / category / order / description / workflow_file / user_facing_inputs / example / fixed_patches / do_not_modify_warnings |
| app/presets/health_requirements.json | ONLY if the workflow adds new model / custom-node deps |

**If a new workflow does not fit existing schema, EXTEND the schema first
  (add a type to _build_input_component, add fields to params.json).
  Do NOT bypass schema with a one-off code path for one workflow.**

### Workflow output node -- when in doubt, ask the user

When a workflow has more than one image / video output node (SaveImage /
PreviewImage / VHS_VideoCombine / etc.), the runner has to pick which one
to display in `output_box`. Don't guess.

**Default protocol when adding / fixing a workflow**:

1. Open the workflow JSON in ComfyUI, identify every output-capable node.
2. For each candidate, look at:
   - node `_meta.title` ("Preview Image" vs "Save Image" vs "Blend" vs "Mask Preview")
   - whether it writes to `output/` (type="output") or `temp/` (type="temp")
   - whether it's an intermediate blend / mask / scale step, or the final render
3. If the answer is unambiguous from titles + storage type -> set it
   directly in `params.json` (e.g. via a `do_not_modify_warnings` entry
   naming "node N = final user-facing output").
4. **If uncertain (e.g. a workflow has 3 PreviewImage nodes plus a SaveImage
   and it's not obvious which one is the final), STOP and ask the author.**
   Phrase the question concretely:
   - "This workflow has image outputs at nodes X, Y, Z. Which one is what
     the user should see in `output_box` after Run?"
   - Or: "I've identified node N as the final image because of <reason>.
     Confirm before I lock it in."

**Why**: image-output selection happens at one chokepoint
(`run_workflow` `output_kind=="image"` branch in `app/scail2_app.py`).
Picking the wrong default silently displays the wrong image (e.g. a SAM
mask instead of the wordcloud), and the user thinks "the workflow broke"
when actually the runner picked the wrong node. Fixing this without
user confirmation is hard-coding the agent's interpretation of the
workflow into the runtime -- which is exactly what "data-driven, no new
code" tries to avoid.

**Don't**:
- Don't auto-pick "the first type=output node" or "node 23 SaveImage" or
  "the one that appears last in the JSON" without a written rationale.
- Don't apply a defensive filter (like the `prefer type=output` image
  fallback) without first checking that no current workflow relies on
  the old behavior.
- Don't ship a workflow whose "which node is the output" answer is "I
  read the JSON and figured it out".

**Exception**: a defensive fix that explicitly mirrors an existing
established pattern (e.g. `extract_primary_video_output` for the video
side, commit 2113045) is fine -- but the rationale must be cited in the
commit message, not just in the code comment.

## Schema design direction -- minimize authoring pain

For each new workflow, the author writes a user_facing_inputs array in params.json.
Each entry needs at least (node_id, field, label, type, tier). This is the heaviest
authoring burden in the project. Convergence directions worth pursuing:

- 'type' is mostly inferrable from the workflow JSON (file:image / file:video / text /
  int / bool / image_sizes). Any direction that cuts required fields is good.
- When adding a new type, FIRST implement it in _build_input_component, only THEN
  let the author use it. Do NOT add a half-working type (current example: the
  'custom WxH comma-separated' branch of image_sizes is unreachable from the UI --
  it's half-working and should be reaped).
- do_not_modify_warnings is a memo for future maintainers, not user config --
  keep it lightweight.
- fixed_patches is a preset-level hardcoded patch (e.g. SCAIL2 two modes share one
  workflow JSON, differ only by patching node 353). This reuse mechanism is good;
  encourage it for new workflows.

## Local dev environment -- `.venv`

A project-local `.venv/` (Python 3.12.10) is the canonical dev environment. It
exists so the bundle launcher can later consume the same Python + deps by
copying the venv contents into its embedded Python distribution.

- `.venv/` is in `.gitignore`; everyone rebuilds from `requirements.txt`.
- Run tests through `.venv\Scripts\python.exe -m pytest tests -q`.
- Never install packages with system `pip` outside the venv -- the launcher
  copies `.venv/` wholesale, system-site-packages leakage will not survive the move.
- `requirements.txt` is the source of truth; if you add a dep, add it there
  AND verify `pip install -r requirements.txt` from a clean venv works.
- `start_webui.bat` is unchanged -- it auto-creates / reuses `.venv` and launches
  from it (the launcher side does not need to know).

## Relationship with the launcher

- port **8199** -- avoids Gradio default 7860 and ComfyUI's 8188.
- WebUI is decoupled from ComfyUI: WebUI failure does not affect ComfyUI; ComfyUI
  being down does NOT prevent opening WebUI (user configures URL in Settings tab).
- Health-check failure must give **actionable diagnosis** (port not listening ->
  'click Start in ComfyUI launcher'; model missing -> 'place X under
  ComfyUI/models/...'); never just 'cannot connect'.
- start_webui.bat pre-cleans PID holding 8199 and auto-pip-installs on first run.
  Do NOT change this behaviour -- the author designed it specifically so
  repeated debugging does not hit port conflicts.

## Defense layers -- do not lightly remove

| Module | What it guards |
| --- | --- |
| app/workflow_validator.py | config drift (params.json vs workflow JSON mismatch) |
| app/health_check.py | user-deploy-env diagnosis (L0 connect / L1 system / L2 model / L3 node) |
| app/history.py | per-run manifest sidecar (audit, replay, history tab data source) |
| app/scail2_app.py:_resolve_example_file | stages ComfyUI input-dir files to .examples_cache/ (Gradio 6 security requires files under CWD) |
| zimage schema wiring (nodes 6 / 13 / 3 / 9) | zimage goes through parse_sizes + extract_all_image_outputs; do not replace with free-text intake |
| app/scail2_app.py:_render_workflow_form / _media_to_html / _run_and_format | UI layer: preset panel rendering, output media -> HTML, status prefix dispatch. Style rules live in [`docs/UI_STYLE.md`](./docs/UI_STYLE.md) |

## UI conventions

The emoji palette (film-frame / framed-picture / rocket / scroll / check / cross / ...),
tab structure, last-run state persistence, and CSS class list are governed by
[`docs/UI_STYLE.md`](./docs/UI_STYLE.md). When adding new buttons, status prefixes, or
categories, register them there before shipping the change.

## Review / editing checklist

- Before suggesting 'add a defensive check', ask: does this assumption hold under the
  trust model above? If not, skip it.
- Before suggesting 'rewrite this helper', read docs/DECISIONS.md first -- every
  decision there has a rationale.
- Before suggesting 'split this module', check whether the data-driven principle
  forbids it -- new functionality should be data-only, not new modules.
- When writing new copy / help text, use **user perspective** (users do not know
  what node ID 367 means). Never leak node numbers into UI copy.


## Known gotcha — wf_radio.change + form state (review 2026-07-11)

`wf_radio.change` 触发 `_auto_load_example(name)`, 旧实现**每一次**都把当前
preset 的所有 input **重置回 example**, 用户上传/输入的内容直接被覆盖.

**触发场景** (用户报告):
  1. 提交动作迁移 (in flight / 已完成)
  2. 切换到角色替换看一眼
  3. 切回动作迁移 → 表单被 example 重置, 上传的图 / 提示词全没

**契约**:
  - 首次切到 preset → auto-load example, 把 preset 加入 `_AUTO_LOADED`
  - 二次切到 (在 `_AUTO_LOADED` 里) → 返回 `gr.update()` 保留用户当前输入
  - 其它 preset → 永远 `gr.update()` 不动它们
  - "加载示例素材" / "加载上次成功参数" / 历史 tab "加载到运行" 也都把
    对应 preset 加入 `_AUTO_LOADED`, 跨切换不丢最后一次显式操作

**位置**:
  - `_AUTO_LOADED` + `_resolve_auto_load_updates` 在 `app/scail2_app.py` 模块级
  - 历史 tab 的 `_stage_rerun` 把 preset 加入 `_AUTO_LOADED` (替代旧 `_SKIP_AUTO_LOAD` 一次性机制)
  - 测试在 `tests/test_preset_switch_preserves_form.py` (11 个 case, 锁契约)

**why we extracted to module-level function**:
  - 原闭包 `def _auto_load_example(name)` 在 `build_ui` 里, 单测拿不到
  - 提取成 `_resolve_auto_load_updates(preset_inputs_map, name)` 之后, 测试用
    `_realistic_preset_inputs_map()` 构造最小 inputs 即可验证契约


## Known gotcha \u2014 ComfyUI /view URL has trailing query params (review 2026-07-11)

`scail2_client.get_output_url` 拼出来的 URL 结构是
  `http://<host>/view?filename=NAME&type=output&subfolder=SUBFOLDER`

旧实现 `_media_to_html` 用 `low_src.endswith(('.mp4', '.mov', ...))` 判断视频.
URL 末尾是 `&subfolder=...` 而不是 `.mp4`, `endswith` 不命中, 误判成
"\u672a\u77e5\u8f93\u51fa\u683c\u5f0f" banner, 用户看不到视频.

**修法**: 新增 helper `_media_ext_from_url(src)`, 解析 URL 提取扩展名:
  1. 本地路径 -> `Path.suffix`
  2. HTTP URL -> 先看 `path.suffix`; 裸端点 (如 /view) 退回 query param
  3. query 里按 `filename` (ComfyUI) -> `f` (测试用) -> `name` -> `file` 顺序找
  4. 兜底: 第一个有扩展名的 query value

**位置**:
  - `_media_ext_from_url` 在 `app/scail2_app.py`, `_media_to_html` 之前
  - `_media_to_html` 里 4 处 `low_src.endswith(...)` 全改成 `ext in (...)`
  - 测试在 `tests/test_ui_helpers.py` 末尾 (7 个新 case, 锁 ComfyUI /view URL 渲染成 <video>)

**为啥不能直接 `endswith` URL**: query string 里 filename 不是 URL 末端子串.


## Project rule -- every preset's `example` IS its default parameters

`example` 字段在每个 preset 上都必须存在, 它是用户打开工作流后**第一眼看到**的参数.
这也是 `wf_radio.change` 切换到任意 preset 时的默认行为. 锁这条契约的
是 `tests/test_preset_must_have_example.py` (5 个 case).

适用范围:
  - 现有: `zimage` / `sca12_motion` / `sca12_replace`
  - 未来新加的所有 preset

`docs/ADDING_WORKFLOWS.md` \u00a74 有完整的 "example 怎么写 / 跑一次生成 preview" 段, 加新 preset 之前先看.


## UI 行为: output_box 默认填 example 预览 (review 2026-07-11)

之前一轮 commit 把\u201c示例预览\u201d独立卡删了 (因为和最终输出区重复). 但默认参数 = example,
跑出来就是 example 里的那张图, \u201c\u8ba9\u522b\u4eba\u76f4\u63a5\u770b\u5230\u201d(\u770b\u5230\u8fd9\u4e2a\u5de5\u4f5c\u6d41\u80fd\u4ea7\u51fa\u4ec0\u4e48) \u662f\u771f\u5b9e\u9700\u6c42.
\u91cd\u65b0\u8868\u8fbe: \u4e0d\u518d\u72ec\u7acb\u5361\u7247, \u76f4\u63a5\u628a example \u7684\u9884\u89c8\u56fe\u586b\u8fdb\u53f3\u680f\u201c\u751f\u6210\u7ed3\u679c\u201d\u533a\u4f5c\u4e3a\u9ed8\u8ba4\u503c.

\u8def\u5f84:
  - `_render_workflow_form` \u91cc\u8bfb example.preview_video / preview_image
  - \u89e3\u6790\u8def\u5f84\uff08\u9879\u76ee\u5185\u8def\u5f84\u6216 http(s) URL\uff09
  - \u751f\u6210 HTML \u586b\u5165 output_box.value
  - \u4e0a\u9762\u6709\u4e2a\u5c0f\u8bf4\u660e \u201c\u793a\u4f8b\u6548\u679c\uff08\u9ed8\u8ba4\u53c2\u6570\u5bf9\u5e94\u7684\u7ed3\u679c\uff09\u201d

\u8dd1\u4e86\u4e4b\u540e:
  - `_run_and_format` \u4e0e _yield_run_stream \u8fd8\u662f\u8d70\u539f\u6709\u8def\u5f91: \u6bcf\u6b21 yield \u90fd\u4f1a\u7528 _media_to_html \u91cd\u7b97 output_box.value
  - \u7b2c\u4e00\u6b21 yield \u5c31\u4f1a\u8986\u76d6\u9ed8\u8ba4\u7684\u793a\u4f8b\u56fe, \u8dd1\u5b8c\u6700\u540e\u4e00\u6b21 yield \u4fdd\u7559\u6700\u540e\u4e00\u5f20\u751f\u6210\u56fe
  - \u4e0d\u9700\u8981\u989d\u5916\u4fee\u6539\u8dd1\u52a8\u903b\u8f91

\u6d4b\u8bd5:
  - tests/test_preset_must_have_example.py \u65b0\u589e 3 \u4e2a case:
    - output_box \u521d\u59cb\u503c\u4e0d\u662f\u5360\u4f4d\u7b26, \u662f example \u9884\u89c8 HTML
    - sca12 \u89c6\u9891\u7c7b preset \u8dd1 <video> \u6807\u7b7e (\u4f18\u5148 preview_video)
    - caption \u5305\u542b \u201c\u9ed8\u8ba4\u53c2\u6570\u5bf9\u5e94\u7684\u7ed3\u679c\u201d

\u8d44\u4ea7:
  - \u6062\u590d\u4e86 sca12_motion_3seg.{png,mp4} / sca12_replace_3seg.{png,mp4} / zimage_720x1280_0001.png
    \u8fd9 5 \u4e2a\u4e0a\u4e00\u8f6e\u5220\u4e86\u7684 preview \u8d44\u4ea7
  - params.json \u91cc\u7684 preview_image / preview_video \u91cd\u65b0\u52a0\u8d70, \u4f5c\u4e3a output_box \u9ed8\u8ba4\u503c\u7684\u6570\u636e\u6e90


## Gotcha: Gradio 6 静态文件路由是 /gradio_api/file=, 不是 /file= (2026-07-11)

**根因**: Gradio 6 把所有 API + 静态文件路由都挂在 `API_PREFIX = "/gradio_api"`
下 (见 `gradio/route_utils.py`)。 也就是说图片/视频要走的路由是:
  - `http://host:port/gradio_api/file=<relative path>`
不是:
  - `http://host:port/file=<relative path>` (这条在 Gradio 6 直接 404)

旧代码 (`app/scail2_app.py:_resolve_preview_path` + `_media_to_html`)
两个地方都返回 `"/file=..."`, 浏览器看到的是破图标。 截图里能看到
"<img src='/file=app/static/examples/...'>" 这条请求返回 404。

**修法**: 定义模块级常量 `_FILE_ROUTE_PREFIX = "/gradio_api/file="`,
两处都改成 `_FILE_ROUTE_PREFIX + rel_path`。 写死 "/gradio_api/" 也行,
但用常量方便未来 Gradio 改了能一处改完。

**分发安全性**:
  - URL 里的路径是 **相对** 的 (`app/static/examples/...`), 不是绝对路径
  - 服务端 Gradio 用 `os.path.abspath()` 把它解析到 `<CWD>/app/static/...`
  - `start_webui.bat` 启动时会 `cd /d "%~dp0"` 到项目根, 所以 CWD 始终是项目根
  - `allowed_paths = config.REPO_ROOT / "app" / "static" / "examples"`
    里的 `REPO_ROOT` 也是从 `config.py` 位置自检 (`Path(__file__).resolve().parent.parent`),
    不依赖任何硬编码绝对路径
  - 结论: 项目挪到 `D:\Other\Path\ComfyUIWebToRunWorkflow` 依然能正常解析

**测试覆盖** (`tests/test_preset_must_have_example.py`):
  - `test_output_box_uses_file_route_not_local_path` 锁住 URL 必须是 `/gradio_api/file=` 前缀
  - 三个 preset (zimage / sca12_motion / sca12_replace) 都覆盖

**排查信号** (以后再遇到类似情况):
  1. 截图里看到破图标 + 旁边有 caption
  2. DevTools Network 看 `<img src=...>` 请求是否 404
  3. 把 `src` 直接复制到地址栏访问, 看是 404 还是 200
  4. 404 → 路由错了, 翻 Gradio 6 文档看实际路由前缀
  5. 200 → 不是路由问题, 是别的 (CORS / 权限 / 文件确实不存在)


## Gotcha — Light mode removed, theme persists across restart (2026-07-12)

**Light mode 整段下线 (per user "明亮模式 很多内容看不清")**

  - tokens.css 删了 `@media (prefers-color-scheme: light)` 块;
    没有 system-follow light、forced light radio 之类
  - scail2_app.py 删 _LIGHT_SURFACE / _list_modes / _apply_mode / _get_mode_desc / _apply_combined
    全部 mode 系统; mode_radio / mode_desc / _on_mode_change 从 settings tab 拿掉
  - 设置 tab 现在只剩 3 个 radio: workflow / sizes / theme
  - 测试: tests/test_css_theming.py 删了 16 个测 light/mode 的 case (Section I/J/K)

为啥砍: probe 显示 light mode 下 `code` 标签用 `--theme-accent-300`(浅橙)在白底上
contrast 1.77, helper descriptions 用 slate-400 contrast 2.43。要修需要给 4 套主题都
重新挑在白底上 contrast ≥ 4.5 的 accent-300/400 + 给 --text-faint / --text-muted
/ 所有 light mode 覆写大幅调整 —— 项目本来就按暗色设计, 改起来得不偿失。
直接砍, 没有"开关", 用户看不到 light 选项。

**主题持久化 (新加)**

  - 文件: `app/data/theme_settings.json` —— schema `{"theme_id": "..."}`
  - 启动期: 5 处 `_DEFAULT_THEME_ID` 改成 `_load_saved_theme()`
    (theme_injector.value / theme_radio.value / theme_desc 等)
  - 用户切主题: theme_radio.change → _on_theme_change 内 `_save_theme(new_tid)`
    → 写盘 → 下次启动沿用
  - 失败兜底契约 (见 tests/test_theme_settings_persistence.py 8 个 case):
    * 文件不存在 / 损坏 JSON / 空对象 / 不在 themes.json 里 → 回退 coral-orange
    * 父目录不存在 → 静默不抛, UI 不崩
    * 不会误改 themes.json (mtime 不变)
  - config.py 加 `THEME_SETTINGS_FILE` path, `.parent.mkdir(...)` 自动创建
  - 路径随项目走 (REPO_ROOT 派生), 项目分发到任意机器都自动落盘到本地

**未来再加 light mode 的前提**

  - 先重做 4 套主题的 light variant tokens.json (accent 需要 dark 饱和度对应物)
  - 再扩 _apply_theme 接受 mode 参数
  - 不能复用现在 4 套主题的 --theme-accent-*, 那批数字 deep sea blue / mint-tesla
    之类饱和度不够, 在白底上至少有一半会跌破 contrast 4.5
