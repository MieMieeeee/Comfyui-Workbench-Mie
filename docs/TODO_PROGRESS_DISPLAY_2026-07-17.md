# 任务进度显示优化 TODO (2026-07-17)

> 对应 review: 2026-07-17 进度显示专项 review (`scail2_app.py` run_workflow /
> run_image_workflow + `scail2_client.py` wait_for_completion)。
> 核心问题: 当前进度条是匀速假进度 (`_wait_p += 0.02`), 跟 ComfyUI 真实执行
> 无关; UI 还泄漏 `node 367` 到状态条 (违反 AGENTS.md "Never leak node numbers")。

每条按 TDD:RED 写测试 -> 看 fail -> GREEN 改最小代码 -> 看 pass -> REFACTOR。
跑 `.venv\Scripts\python.exe -m pytest tests -q` 验证。

## 进度总览

| 优先级 | 项 | 状态 | 测试文件 |
| --- | --- | --- | --- |
| P1 | 节点号 -> `_meta.title` 映射 (消 node 泄漏) | DONE | tests/test_node_title_map.py |
| P0 | WebSocket 真实 step 进度 (value/max) | DONE | tests/test_ws_progress_listener.py |
| P2 | 三层进度信息去重 + gr.Progress 用真实百分比 | DONE | tests/test_progress_bar_real_percent.py |
| P3 | 多尺寸文生图总进度 (segment + step 合成) | DONE | tests/test_image_workflow_total_progress.py |
| CSS | `.run-status-progress` 百分比胶囊样式 | DONE | tests/test_run_status_progress_capsule.py |
| DEP | `websockets>=12.0` 加到 requirements.txt | DONE | (验证: venv 16.1 import OK) |

执行顺序: P1 (无依赖) -> P0 (核心, ws) -> P2 (依赖 P0) -> P3 (依赖 P0) -> CSS -> DEP。
最终: 497 passed / 9 skipped (baseline 461 -> +36 新增, 0 回归)。

## 每项详细记录

### P1 (DONE) — node_id -> title 映射

- RED: 8 tests fail (`build_node_title_map` 不存在, `_last_executed_node` 不接 title_map).
- GREEN (app/scail2_client.py):
  - 新增 `build_node_title_map(workflow)`: 三级回退 (`_meta.title` -> `class_type` -> node_id).
  - 改 `_last_executed_node(history, title_map=None)`: 有 map 返 title (缺失回退 id),
    无 map 保持 `"node {id}"` (向后兼容锁).
- 调用点 (app/scail2_app.py): run_workflow 在 `patched` 后建 `_title_map`;
  run_image_workflow 在 `wf_base` 后建一次 (尺寸循环外).
- Verify: 9 new tests pass + full suite 470 passed / 9 skipped.

### P0 (DONE) — WebSocket 真实 step 进度

- RED: 12 tests fail (`_parse_ws_event` / `start_progress_listener` 不存在,
  `wait_for_completion` 不接 `progress_queue`, `queue_prompt` 返 str 不返 tuple).
- GREEN (app/scail2_client.py):
  - imports 加 `asyncio` / `queue` / `threading` + try-import `websockets` (失败设
    `_websockets_available=False`, 不抛).
  - `_parse_ws_event(msg)`: 纯函数解析 progress/executing/done, 未知返 None.
  - `_ws_loop(base_url, client_id, event_queue)`: daemon 线程的 asyncio 入口,
    `async with websockets.connect(ws?clientId=)`, 读消息塞队列, sentinel None 退出.
  - `start_progress_listener(client_id, base_url=None) -> queue.Queue`: 启动 daemon
    线程, websockets 没装/client_id 空 -> 返空队列不抛 (降级契约).
  - `wait_for_completion(prompt_id, title_map=None, progress_queue=None)`:
    每次 poll 前 `_drain_progress()` 更新 `cur_progress=(value,max)` (只增不减防倒退),
    yield 时拼 `"⏳ MM:SS  running…  {title} {value}/{max}"`; 无 progress 跟现状一致.
  - `queue_prompt(workflow, client_id=None) -> tuple[str, str]`: 返 `(prompt_id, client_id)`,
    调用方拿 client_id 喂 listener.
- 调用点 (app/scail2_app.py): run_workflow + run_image_workflow 都 `try: ... finally: _pq.put(None)`
  通知 ws 线程退出 (防泄漏).
- 现有测试 mock 更新: 7 个测试文件的 `queue_prompt` mock 从返 str 改成返 tuple,
  全部加 `start_progress_listener` mock 返空队列 (不开真线程).
- smoke/e2e 脚本 (integration_smoke_client.py / run_e2e_real.py) 解包改成 `(prompt_id, client_id)`.
- Verify: 12 new tests pass + full suite 482 passed / 9 skipped.

### P2 (DONE) — 三层进度信息去重 + gr.Progress 真实 %

- RED: 6 tests fail (`_extract_step_progress` 不存在, run_workflow 仍用 `_wait_p += 0.02`).
- GREEN (app/scail2_app.py):
  - 新增 `_STEP_PROGRESS_RE` + `_extract_step_progress(status_msg) -> (value, max) | None`:
    正则抽 msg 里最后一个 `value/max` (max>0), 时间戳 MM:SS 不误匹配.
  - run_workflow 等待循环: 有 step 用 `0.45 + ratio*(0.92-0.45)` 真实映射, 无 step 才回退 `+=0.02`.
  - _render_status_html 调用点 (_run_and_format 闭包): 抽 step 算百分比喂状态条胶囊.
- 注: status_box (日志) 累积多行, status_bar 显示最新一条 — 现有 `_yield_run_stream` 已做累积,
  无需改. 这条契约靠既有测试覆盖.
- Verify: 6 new tests pass + full suite 488 passed / 9 skipped.

### P3 (DONE) — 多尺寸文生图总进度

- RED: 1 test fail (seg2 内 step 10/20 仍显示 `_seg_p += 0.02` 的 0.353, 期望 ~0.5).
- GREEN (app/scail2_app.py: run_image_workflow 内循环):
  - 尺寸区间 `[(idx-1)/n, idx/n]` 保留.
  - 尺寸内进度: 有 step 用 `seg_start + ratio*(seg_end-seg_start)` (真), 无 step 才 `+=0.02`.
- Verify: 2 new tests pass + full suite 494 passed / 9 skipped.

### CSS (DONE) — `.run-status-progress` 百分比胶囊

- RED: 6 tests fail (CSS 块不存在, _render_status_html 不接 progress_str).
- GREEN:
  - app/static/tokens.css 加 `.run-status-progress` 块: mono / text-xs / 主题色边框 +
    `--theme-accent-glow` 半透明填充 / flex-shrink:0 (跟 `.run-status-elapsed` 同风格).
  - app/scail2_app.py `_render_status_html(state, msg, elapsed_str='', progress_str='')`:
    有 progress_str 渲染 `<span class="run-status-progress">`, 空串不渲染 (向后兼容).
    位置: elapsed 之后 (单行 flex 最右).
- Verify: 7 new tests pass + full suite 497 passed / 9 skipped.

### DEP (DONE) — `websockets>=12.0` 加到 requirements.txt

- requirements.txt 加 `websockets>=12.0` (用 >=12.0 而非 >=16: 只依赖 asyncio connect API,
  v12+ 就稳定; 宽下限对 launcher 嵌入式 Python 更友好).
- 验证: `.venv` 里是 16.1 (transitive via gradio/fastapi), import OK.
- AGENTS.md 契约: requirements.txt 是唯一真相来源, 显式登记避免 gradio 升级砍掉 fastapi 时悄悄丢.

---

## 不改的东西 (锁定的契约)

- `wait_for_completion` 同步 `Iterator[str]`, 签名只加 optional kwargs
- emoji 前缀协议 (`⏳`/`✅`/`❌`/`⏰`) 不变
- `run-status-bar` 单行 flex 布局不变
- 历史记录 / 设置 tab / 主题系统完全不动

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| ws 后台线程泄漏 (任务取消) | `daemon=True` + `wait_for_completion` finally 里 `progress_queue.put(None)` 通知退出 |
| ws 连不上导致测试卡住 | 测试 mock `start_progress_listener` 返回空队列, 不开真线程; 真连不上有 connect_timeout |
| websockets 16.x API 变化 | 用 `asyncio.run` + `async with websockets.connect(...)` 现代写法, 封装在 `_ws_loop` 单函数 |
| 进度值倒退 (cache hit) | progress 值只增不减 (max(seen, new)), 完成时强制 1.0 |
| `_meta.title` 为中文/emoji | 直接显示, 不转义 (span 包裹, 浏览器原生支持) |
