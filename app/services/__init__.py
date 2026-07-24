"""app.services — 纯业务逻辑层 (无 web 框架依赖).

Flask 路由 (app/flask_app.py) 调这些函数, 不直接碰 ComfyUI client / 文件系统.
Gradio 时代这些函数在 scail2_app.py 里 (已删除), migrate-to-flask 抽到这里.

子模块:
  status       — 状态字符串解析 (_extract_status_kind / _phase_from_status / ...)
  media        — media → HTML (_media_to_html / _media_ext_from_url / _local_to_url)
  theme        — 主题加载/持久化/应用 (_apply_theme / _load_saved_theme / ...)
  persistence  — last_run 持久化
  form_schema  — preset spec ↔ 表单值 (example_to_form_values / parse_sizes / ...)
  runner       — run_workflow / stream_events (yield RunEvent 给 SSE)
"""
