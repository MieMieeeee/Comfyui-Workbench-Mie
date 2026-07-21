# 计划: Gradio → Flask + Alpine.js + SSE 迁移

> 分支: `migrate-to-flask`(从 master `d79f70a` 切出)
> 创建: 2026-07-21
> 节奏: **一次性切换**(用户已确认接受中间不可用 + 测试真空期风险)
> 每步独立提交,失败可 bisect;每步完成更新本文档勾选状态。

## 技术栈

- **后端**: Flask + SSE(Server-Sent Events)
- **前端**: Alpine.js(本地引入 `static/alpine.min.js`,~15KB,无 build step)+ 原生 HTML/CSS/JS
- **流式**: SSE 对应现在 43 处 yield
- **业务逻辑**: `run_workflow` / `run_image_workflow` / `parse_sizes` / `_media_to_html` / `scail2_client.*` / `history.*` / `health_check.*` 全部复用

## 代码边界(来自 subagent 边界报告)

| 文件 | 耦合度 | 处置 |
|---|---|---|
| `app/config.py` (141 行) | 仅 2 常量名带 GRADIO | 改 2 个常量名 |
| `app/scail2_client.py` (622 行) | **零耦合** | 原封不动复用 |
| `app/history.py` (159 行) | **零耦合** | 原封不动复用 |
| `app/health_check.py` (252 行) | **零耦合** | 原封不动复用 |
| `app/workflow_validator.py` | **零耦合** | 原封不动复用 |
| `app/scail2_app.py` (2605 行) | 重度耦合 | 拆分: ~50% 抽 services, ~50% 重写 |

## 目标目录结构

```
app/
  config.py                 # 改 2 个常量: GRADIO_HOST/PORT → FLASK_HOST/PORT
  scail2_client.py          # 零改动
  history.py                # 零改动
  health_check.py           # 零改动
  workflow_validator.py     # 零改动

  services/                 # 新建: 从 scail2_app.py 抽出的纯业务逻辑
    __init__.py
    runner.py               # run_workflow / run_image_workflow 去 gr.Progress/gr.Error,
                            # yield 纯 RunEvent 数据类
    form_schema.py          # example_to_form_values / _manifest_to_form_values /
                            # _resolve_upload_name / _is_comfy_input_file /
                            # validate_inputs / parse_sizes / estimated_segments /
                            # get_video_frames
    persistence.py          # _save_last_run / _load_last_run / _save_theme / _load_saved_theme
    theme.py                # _apply_theme / _build_launch_css / _build_launch_head /
                            # _list_themes / _load_tokens_css / _get_theme_desc
    media.py                # _media_to_html (改 _FILE_ROUTE_PREFIX → Flask url)
    status.py               # _extract_status_kind / _phase_from_status /
                            # _extract_step_progress / _format_elapsed / _failure_hint

  flask_app.py              # 新建: Flask app + 路由 + SSE generator
  templates/
    base.html               # 全局 layout (head + theme injection + Alpine)
    run.html                # 运行 tab(导航 + 工作流表单 + 结果区)
    settings.html           # 设置 tab(URL/主题/健康检查)
    partials/
      _preset_panel.html    # 单个 preset 表单(Jinja2 for-loop 渲染 spec)
      _status_bar.html
      _task_list.html
  static/
    tokens.css              # 复用,清 !important(DOM 不再被 Gradio 包裹)
    app.js                  # Alpine components + SSE EventSource + fetch helpers
    alpine.min.js           # 本地引入(CDN 下载一次)
    examples/               # 不动

  scail2_app.py             # 步骤 7 删除
```

## 关键架构决策

### 1. RunEvent 数据类取代 6-tuple/7-tuple

```python
@dataclass
class RunEvent:
    type: Literal["log", "media", "error", "done"]
    log: str | None
    media_url: str | None
    media_html: str | None
    error_html: str | None
    state: str | None              # idle/running/success/failure/timeout
    elapsed_sec: float | None
    progress: tuple[int, int] | None
```

`_yield_run_stream` 改名 `_stream_events`,yield RunEvent,Flask 路由转 SSE JSON。

### 2. SSE 流式协议

```python
@app.route("/api/run/<preset_name>", methods=["POST"])
def run_preset(preset_name):
    vals = _collect_form_values(request.json, request.files, preset_name)

    def event_stream():
        for ev in _stream_events(run_fn, preset_name, vals, output_kind=...):
            yield f"data: {json.dumps(asdict(ev))}\n\n"
        yield "data: [DONE]\n\n"
    return Response(event_stream(), mimetype="text/event-stream")
```

前端用 `fetch + ReadableStream`(POST 不能用 EventSource)。

### 3. 静态资源路由

- `_FILE_ROUTE_PREFIX = "/gradio_api/file="` → 删
- Flask `url_for('static', filename=...)` 处理仓库内文件
- ComfyUI input 目录文件: `/comfy_input/<filename>` 路由
- **删除** `_resolve_example_file`(Gradio 6 安全 workaround,Flask 不需要)

### 4. 文件上传(替代 gr.File)

`/api/upload` 接 multipart,保存到临时目录,调 `scail2_client.upload()`,返回 ComfyUI 的 name。前端 `<input type="file">` + Alpine `x-model`。

### 5. 主题切换

`_apply_theme` 返回 `<style>:root{...}</style>` 字符串,Flask 在 `base.html` 的 `<head>` 里 `{{ theme_css|safe }}` 注入。**删掉** `theme_injector = gr.HTML(...)` 机制。

### 6. 表单组件(spec.type → HTML)

Jinja2 macro 替代 `_build_input_component` / `_create_one_input`:
- `file:image` / `file:video` → `<input type="file" accept="...">`
- `text` / `prompt_pool` → `<textarea>`
- `image_sizes` → `<fieldset>` 多 checkbox
- `int_random` → checkbox + number
- `select` → `<select>`
- `bool` → `<input type="checkbox">`
- `int` → `<input type="number">`
- `prompt_pool` 的随机按钮 → Alpine `@click="fetch('/api/random_prompt')"`

## 21 处事件绑定 → Flask 路由映射

| Gradio 事件 | 处置 |
|---|---|
| run_btn.click(generator) | `/api/run/<preset>` POST + SSE |
| re_run_btn.click | 同上 |
| ex_btn.click | `/api/example/<preset>` GET |
| last_btn.click | `/api/last_run/<preset>` GET |
| open_dir_btn.click | `/api/open_output_dir` POST |
| comp.change(缩略图) | **前端** `URL.createObjectURL(file)` |
| rand_btn/rand3_btn.click | `/api/random_prompt` / `?n=3` GET |
| _trigger.change(段数预估) | `/api/estimated_segments?frames=...` GET |
| save_btn/reset_btn/retest_btn | `/api/settings/url*` POST/GET |
| full_check_btn.click | `/api/health` GET |
| theme_radio.change | `/api/theme` POST |
| wf_search.change | **前端** 纯 JS 过滤 |
| refresh_status_btn.click | `/api/comfy_status` GET |
| open_output_btn.click | `/api/open_output_folder` POST |
| wf_radio.change(切 panel) | **前端** Alpine `x-show` |
| wf_radio.change(自动 example) | **前端** Alpine `x-init` 首次切到调 `/api/example/<preset>` |
| demo.load | base.html 服务端渲染初始数据 |
| _switch_panel | **前端** Alpine |

**~10 处纯前端处理,只剩 11 个真实后端路由**。

## 测试策略

| 类别 | 处置 |
|---|---|
| 纯函数测试 (test_patch_workflow / test_validator / test_health_check / test_prompts / test_estimated_segments / test_node_title_map / test_also_patch / test_fixed_patches_and_example / test_new_presets_from_comfyui_skill / test_config_list_workflows / test_display_name_normalization 等 ~100 个) | **保留**,继续跑 |
| Gradio UI 测试 (test_run_workflow_* / test_e2e_render / test_build_form / test_css_theming / test_layout_polish_* 等) | 归档到 `tests/_archive_gradio/` |
| 新写 Flask 测试 | `test_flask_routes.py` / `test_sse_stream.py` / `test_form_schema.py` / `test_runner_events.py` / `test_flask_e2e.py` |

## 执行步骤(每步独立 commit)

- [ ] **步骤 0**: 创建本计划文件 + 提交到 migrate-to-flask 分支
- [ ] **步骤 1**: 抽 `services/`(纯重构,Gradio 版仍跑,所有现有测试继续 GREEN)
  - 新建 `app/services/{__init__,runner,form_schema,persistence,theme,media,status}.py`
  - 把对应函数从 `scail2_app.py` 移过去,`scail2_app.py` 改成 `from app.services import ...`
  - 跑全量测试确认 GREEN
- [ ] **步骤 2**: 建 `flask_app.py` + 非流式路由
  - `/api/theme` / `/api/example/<preset>` / `/api/last_run/<preset>` / `/api/comfy_status` / `/api/settings/url*` / `/api/health` / `/api/random_prompt` / `/api/estimated_segments` / `/api/open_output_dir` / `/api/open_output_folder`
  - 每个 route 配套 TDD 测试
- [ ] **步骤 3**: 建 `templates/` + `static/app.js` + Alpine UI
  - `base.html` / `run.html` / `settings.html` / `partials/_*.html`
  - 下载 `alpine.min.js` 到 `static/`
  - Jinja2 macro 渲染 spec → 表单字段
- [ ] **步骤 4**: 接 SSE 流式 `/api/run/<preset>`
  - RunEvent 数据类 + `_stream_events` 生成器
  - Flask `Response(generate(), mimetype='text/event-stream')`
  - 前端 `fetch + ReadableStream` 接收
- [ ] **步骤 5**: 文件上传路由 `/api/upload`
  - multipart 处理 + 调 `scail2_client.upload()`
  - 前端 `<input type="file">` + 缩略图 `URL.createObjectURL`
- [ ] **步骤 6**: 切换 main 入口到 `flask_app`
  - `app/flask_app.py` 加 `if __name__ == "__main__"` 启动逻辑
  - `start_webui.bat` 改为调 `flask_app`
- [ ] **步骤 7**: 下线 Gradio
  - 删 `app/scail2_app.py`
  - `requirements.txt`: 去掉 `gradio>=6.0`,加 `flask>=3.0`
  - Gradio 测试归档到 `tests/_archive_gradio/`
- [ ] **步骤 8**(可选): CSS 瘦身
  - 清掉 `tokens.css` 里 Gradio 专用的 `!important` 和 `.svelte-xxx` 选择器
  - 独立后续工作,不阻塞迁移

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| SSE 在某些代理/浏览器下不工作 | 可选 fallback 轮询(默认不实现) |
| Flask dev server 单线程阻塞 SSE | `app.run(threaded=True)` 或 waitress |
| Alpine 引入违反 "no new code" 原则 | 该原则针对业务逻辑,前端框架是基础设施,不冲突 |
| `.venv` 整体复制给 launcher 时 Flask 不在 requirements | 步骤 7 同步更新 requirements.txt |
| 测试真空期 | 步骤 1 纯重构测试全程 GREEN;步骤 2-7 每步同步写 Flask 测试 |

## 工作量估算

- 步骤 1: ~3-4 小时(纯重构,风险低)
- 步骤 2-3: ~6-8 小时(主要工作量)
- 步骤 4: ~2-3 小时
- 步骤 5: ~1-2 小时
- 步骤 6-7: ~1-2 小时
- 步骤 8: ~2-3 小时(可后续)
- **总计 ~15-22 小时**

## 进度日志

(每完成一步在此追加)

### 2026-07-21
- baseline 确认: master `d79f70a`, 554 passed / 3 skipped
- 切出分支 `migrate-to-flask`
- 创建本计划文件
