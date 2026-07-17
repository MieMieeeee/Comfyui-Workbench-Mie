# UI Review 修复 TODO (2026-07-17)

> 对应 review: [UI_REVIEW_2026-07-17.md](./UI_REVIEW_2026-07-17.md)

每条按 TDD:RED 写测试 -> 看 fail -> GREEN 改最小代码 -> 看 pass -> REFACTOR。

## 进度总览

| 优先级 | 项 | 状态 | 测试文件 |
| --- | --- | --- | --- |
| P0-2 | 移除 nav Radio 英文 category 后缀 | DONE | tests/test_wf_label_no_category_suffix.py |
| P0-1 | 历史 tab 启动时自动加载 | DONE | tests/test_history_loads_on_startup.py |
| P1-3 | --text-faint 提亮 (>=3.8 contrast on --bg-card) | DONE | tests/test_tokens_css_text_faint_contrast.py |
| P2-4 | .gradio-container max-width >= 1600 | DONE | tests/test_tokens_css_container_max_width.py |
| P2-5 | build_ui 顶部加 app 标题 h1 | DONE | tests/test_build_ui_has_h1_title.py |
| P2-6 | .custom-radio label padding 紧凑 (review 跟 P0-2 联动) | DONE | tests/test_tokens_css_radio_label_padding.py |
| P3-7 | body { background: var(--bg-app) !important } | DONE | tests/test_tokens_css_body_bg.py |
| P3-9 | 状态条 idle 文案加标点 | DONE | tests/test_status_bar_idle_punctuation.py |
| P3-8 | 449 个 !important 审计 (文档级) | DONE | docs/AUDIT_css_important_count.md |

## 每项详细记录


### P3-8 (DONE, audit only)

- Wrote [docs/AUDIT_css_important_count.md](./AUDIT_css_important_count.md) capturing:
  - Current count: 451 !important across 113 selectors (review measured 449)
  - Top offenders: btn-run-primary/secondary (11 each), history-filter-status (10), sizes-cards / run-status-bar / custom-radio label (9 each)
  - Risk vectors for Gradio 7 upgrade and inline `<style>` arms race
  - Recommendation: don't add new !important without checking specificity; prefer --tokens for one-place changes
- No code changes -- review explicitly says 'not now, worth recording'. Audit is the recording.

### P3-9 (DONE)

- RED: 2 tests fail -- rendered text concatenates label and msg with no separator (`等待运行点击下方按钮开始` reads as one mashed sentence).
- GREEN: in `_render_status_html`, insert a ` · ` span between the state label span and msg span. Only added when msg is non-empty (so an idle with no msg stays clean).
- Implementation note: also fixed a typo in test input (had `资料` instead of `素材` in the load-example copy).
- Verify: 2 new tests pass + full suite 446 passed / 3 skipped.

### P3-7 (DONE)

- RED: 1 test fails -- tokens.css has no explicit `body { background: var(--bg-app) !important; }` rule.
- GREEN: added the rule at the top of tokens.css (above `.gradio-container`). Inline comment notes the Gradio 6 priority-fight rationale.
- Verify: 1 new test pass + 74 CSS tests still pass.

### P2-6 (DONE)

- RED: 1 test fails -- .custom-radio label padding still `var(--space-3) var(--space-4)` (12px / 16px), not compact.
- GREEN: bumped `.custom-radio label` vertical padding from `var(--space-3)` (12px) to `var(--space-2)` (8px). Horizontal also `space-3` (12px) per review.
- Implementation note: first apply script accidentally also changed `.custom-accordion > .label-wrap` (same 3-line pattern). Reverted that one to keep P2-6 surgical -- only `.custom-radio label` got the compact padding.
- Verify: 1 new test pass + 74 CSS tests still pass (custom-accordion unchanged).
- Combined with P0-2 (suffix removed), each nav Radio row should now fit in ~40px single-line.

### P2-5 (DONE)

- RED: 2 tests fail with `build_ui() did not register an h1 (Markdown value starting with '# ')`.
- GREEN: added `gr.Markdown("# 🎬 ComfyUI 工作流运行器")` between theme_injector and the main Tabs.
- Verify: 2 new tests pass + full suite 442 passed / 3 skipped.
- Test approach: inspects `demo.blocks` (Gradio component registry) for a Markdown whose value starts with `# `. Survives refactors (e.g. extracting _render_header).

### P2-4 (DONE)

- RED: `test_gradio_container_max_width_is_wide_enough` fails (current 1400 < 1600 floor).
- GREEN: bumped `.gradio-container { max-width: 1400px }` -> 1700px. Chose 1700 as the midpoint of reviewer's 1600-1800 range.
- Verify: 1 new test pass + 73 CSS tests still pass.

### P1-3 (DONE)

- RED: `test_text_faint_meets_minimum_contrast_on_card_bg` fails (current 2.85 < 3.8 floor).
- GREEN: bumped --text-faint from #5f6470 (2.85) to #767c8a (4.04). Verified with WCAG calc:
  - #5f6470 -> 2.85 (original, fail)
  - #717785 -> 3.76 (reviewer suggested, slightly under)
  - #767c8a -> 4.04 (chosen, just over 3.8 + still distinct from --text-muted 5.27)
- Verify: 2 new tests pass + 81 CSS-related tests pass.
- Note: did NOT merge into --text-muted (review alternative). The dimmer tier is needed for disabled state semantics.

### P0-1 (DONE)

- RED: 2 tests fail with `demo.load did not register _refresh_history_filtered`.
- GREEN: changed `_build_history_tab()` signature to `_build_history_tab(demo)`, added `demo.load(fn=_refresh_history_filtered, inputs=event_inputs, outputs=event_outputs)` after the existing 3 click/change hooks, updated call site in build_ui.
- Side fix: updated `tests/test_css_theming.py::test_history_dataframe_has_custom_dataframe_class` to pass `demo` arg.
- Verify: 2 new tests pass + full suite 437 passed / 3 skipped (test_e2e_browser / run_e2e_real / integration_smoke_client ignored -- need live server).
- Gradio 6 marker used by test: `demo.fns[i].targets == [(0, 'load')]` is how demo.load registers itself.

### P0-2 (DONE)

- RED: 4 tests fail with `AttributeError: module 'app.scail2_app' has no attribute '_wf_label'` (closure not at module level).
- GREEN: extracted `_wf_label(w)` to module level next to `_category_icon`, removed `suffix = f" \u00b7 {cat}"` line, updated call site in build_ui.
- Verify: 4 new tests pass + 84 existing tests in test_preset_switch_preserves_form.py + test_e2e_render.py still pass.
- Note: P2-6 nav row height drop is the natural follow-up (each item now ~40px single-line).

每完成一项,会在该项下追加 RED / GREEN / 验证三段日志。

## Final Summary

All 9 review items resolved. 8 code fixes + 1 doc audit. Final test count: 446 passed / 3 skipped (e2e tests requiring live server ignored).

**Code changes:**
- `app/scail2_app.py`: extracted `_wf_label` to module level (removes suffix), `_build_history_tab(demo)` adds `demo.load(...)`, added app-title h1 in build_ui, `_render_status_html` inserts `·` separator.
- `app/static/tokens.css`: `--text-faint` 5f6470 -> 767c8a (contrast 2.85 -> 4.04), `.gradio-container` max-width 1400 -> 1700, `.custom-radio label` padding vertical 12px -> 8px, added `body { background: var(--bg-app) !important }` rule.
- `tests/test_css_theming.py`: updated one existing call site to new `_build_history_tab(demo)` signature.

**New test files (each locks one review item):**
- `tests/test_wf_label_no_category_suffix.py` (P0-2)
- `tests/test_history_loads_on_startup.py` (P0-1)
- `tests/test_tokens_css_text_faint_contrast.py` (P1-3)
- `tests/test_tokens_css_container_max_width.py` (P2-4)
- `tests/test_build_ui_has_h1_title.py` (P2-5)
- `tests/test_tokens_css_radio_label_padding.py` (P2-6)
- `tests/test_tokens_css_body_bg.py` (P3-7)
- `tests/test_status_bar_idle_punctuation.py` (P3-9)

**New doc:**
- `docs/AUDIT_css_important_count.md` (P3-8)

### P0-1 follow-up: _make_detail_from_run NameError fix (DONE)

Discovered while running E2E browser test: P0-1 (demo.load on history tab) exposed a latent bug.

- Symptom: on first page load, Gradio toast pops `NameError: name 'output_kind' is not defined` in `_make_detail_from_run:1021`.
- Root cause: `_make_detail_from_run` referenced `output_kind` as a closure variable, but it was never defined. Before P0-1, this code path was only reachable via manual `refresh_btn.click`, so the bug stayed latent for any session that didn't manually open history.
- RED: 3 new tests in `tests/test_history_detail_nameerror.py` call `_make_detail_from_run` with image / video / audio runs -- all fail with NameError. The 4th test (empty run) passes (early-return path doesn't hit the bug).
- GREEN: derived `output_kind` from `_output_kind(config.preset_config(run.get('preset')))` with a `video` fallback for unknown presets. Also switched the local `is_image` to use the derived output_kind for consistency.
- Verify: 4 new tests pass + full suite 450 passed / 3 skipped + E2E 6 passed.
- Note for future maintainers: if you find another function referencing a free variable that was only reachable via a rare user action, `demo.load` will surface it on every page load. Treat any reference to a non-local name as a smell.

**Why the headless E2E tests didn't catch this initially:** the project's `tests/test_e2e_browser.py` checks page render + JS errors + key UI elements, but does NOT scan for Gradio toast error messages. Adding a toast-capture check (or running the deep `app/data/probe_e2e_2026-07-17/probe_e2e_toast.py` probe regularly) would catch this category earlier.
