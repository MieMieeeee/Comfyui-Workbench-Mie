"""app.services — 从 scail2_app.py 抽出的纯业务逻辑(无 Gradio 依赖).

迁移到 Flask 期间, scail2_app.py 通过 `from app.services.xxx import ...`
re-export 这些函数, 保持 Gradio 版继续可跑. Flask 版直接 import 用.

子模块:
  status       — 状态字符串解析 (_extract_status_kind / _phase_from_status / ...)
  media        — media → HTML (_media_to_html / _media_ext_from_url)
  theme        — 主题/launch CSS (_apply_theme / _build_launch_css / _build_launch_head / ...)
  persistence  — last_run / theme_settings 持久化
  form_schema  — preset spec ↔ 表单值 (example_to_form_values / parse_sizes / ...)
  runner       — run_workflow / run_image_workflow (步骤 4 改 yield RunEvent)
"""
