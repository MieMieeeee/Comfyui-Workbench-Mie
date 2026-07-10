# History tab UI rework (2026-07-10)

按 review 的 5 个优先改动项重做历史记录 tab。

## 改动

| 项 | 改动 |
|---|---|
| 布局 | 两栏 (左 7 / 右 5)：Dataframe + 详情卡片 |
| 表格列 | 从 10 列精简到 6 列：[时间, 状态, preset, 耗时, prompt, id] |
| 状态列 | 返回 HTML badge (`<span class="status-badge status-badge-{status}">`),Dataframe 用 `datatype=["str","html",...]` 渲染 |
| 详情 | 拆成 `summary_html` (badge + 关键字段网格 + 提示词摘要) + `media_html` (输出预览) + `prompt_md` (提示词全文, accordion) + `detail_manifest` (隐藏 JSON, 喂 rerun) |
| 筛选条 | 一行:Preset dropdown + 状态 pills + "共 N 条" + 刷新按钮 |
| 错误显示 | `.detail-error` 红底高亮 |

## 新增 helper

- `_status_label(status)` - 中文短标签
- `_fmt_time(iso)` - 精简到分钟
- `_truncate(text, max_len)` - 字符串截断
- `_escape(text)` - 轻量 HTML 转义
- `_render_summary_html(badge, fields, prompt)` - 拼装详情卡片
- `_wrap_prompt_markdown(text)` - 把 prompt 包成 markdown 代码块

## 新增 CSS 类 (tokens.css)

- `.status-badge` + `.status-badge-success/failure/timeout/running/unknown`
- `.history-filter-bar` / `.history-filter-preset` / `.history-filter-status` / `.history-count`
- `.history-detail-col`
- `.detail-empty` / `.detail-card` / `.detail-header` / `.detail-fields` / `.detail-field` / `.detail-label` / `.detail-value` / `.detail-error` / `.detail-prompt` / `.detail-prompt-body`

## 已知遗留

- 6 列宽度配比 + `wrap=True` 导致 `sca12_motion` preset 名被换行。
  后续 preset 名超过 ~10 字符时考虑: 改 `wrap=False` + preset 列固定 px 宽。
- Dataframe 顶部 toolbar (复制 / 全屏按钮) 在浅色 hover 时仍偏暗,
  下次统一美化时一起处理。

## 截图

docs/figures/history/history_dark_final.png (主要参考)
docs/figures/history/history_filter_failure_dark.png (验证错误高亮)
docs/figures/history/history_row_selected_dark.png (验证选中行详情)
docs/figures/history/history_light.png (light mode, content 渲染 OK 但 token.css 需要 mode=light 才能切浅底)