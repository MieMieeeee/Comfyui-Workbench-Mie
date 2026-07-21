# Gradio 版测试归档 (2026-07-21 migrate-to-flask)

这些测试是 Gradio 版 (`app/scail2_app.py`) 的测试, 在 migrate-to-flask 分支
彻底下线 Gradio 后归档到此目录.

## 为什么归档

- `app/scail2_app.py` 已删除, 这些测试的 `from app import scail2_app` 会 ImportError
- 它们测的是 Gradio 组件树 (`gr.Blocks` / `gr.Button` / generator yield 6-tuple / 7-tuple
  结构), 不适用于 Flask + Alpine + SSE 架构
- e2e/integration 测试 (test_e2e_browser / test_e2e_render / test_e2e_theme_native_buttons /
  integration_smoke_client / run_e2e_real) 用 playwright 连 Gradio server, Flask 版
  端口/路由不同, 需重写

## 如何恢复某个测试

如果某测试的核心断言对 Flask 版仍有效 (例如纯函数行为), 可以:
1. 从此目录 copy 回 tests/
2. 改 `from app import scail2_app` 为对应 services 子模块:
   - 状态解析       -> `from app.services import status`
   - 主题/CSS       -> `from app.services import theme`
   - 表单/校验      -> `from app.services import form_schema`
   - 持久化         -> `from app.services import persistence`
   - 媒体渲染       -> `from app.services import media`
   - 运行编排       -> `from app.services import runner`
3. 跑测试确认 GREEN

## 新测试位置

Flask 版测试在 tests/test_flask_routes.py (26 case, 路由 + SSE + 上传).
