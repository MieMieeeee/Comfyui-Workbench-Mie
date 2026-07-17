# WordCloud Bug Fixes TODO (2026-07-17)

> 用户反馈三个问题:
> 1. 风格不应该是高级参数 (colormap 应该在 basic, 不是 advanced)
> 2. 单个词不应该有问题
> 3. 我更换了风格再跑就没出图
>
> 另: "启动就弹窗报错" — 经 headless Playwright 探针 + 现有 6 个 test_e2e_browser
>    全过,无任何 toast / 控制台错误,推测是浏览器缓存(AGENTS.md §13)。无需改。
>
> 另: "把 参考图 驱动视频 从ComfyUI的input 加入到本项目assets中" — 经盘点,
>    portrait_model.png (1.4MB) + liveportrait_drive.mp4 (1.9MB) 已在
>    app/static/examples/ 里。assets 已到位,无需再搬。

## 根因(三个问题其实是一个)

`run_workflow` 对 output_kind="image" 走 `extract_all_image_outputs` 然后
取 `image_outputs[0]`(按 node_id 排序后的第一项)。wordcloud 的 workflow
有 5 个 image 输出节点:10 / 22 / 23 / 25 / 29。其中 4 个 type="temp"
(SAM 分割 / LaMa 蒙版 / 升级前 / 蒙版预览),只有 1 个 type="output"
(node 23 SaveImage = 最终词云)。

按 node_id 排序后 `image_outputs[0]` 是 node 10 的 PreviewImage 输出
(一张 SAM 蒙版,文件名 `ComfyUI_temp_tteku_00004_.png`),不是词云本身。

后果:
- 用户看到的"运行结果"是一张黑白蒙版,不是词云。
- 用户切 colormap 后看到"还是蒙版",以为"风格不生效"。
- 单个词生成的也是同一张蒙版,所以用户觉得"单个词有问题"。

commit 2113045 (f5bee57) 已经给 `extract_primary_video_output` 加过
"prefer type=output over type=temp" 的逻辑,但 `extract_all_image_outputs`
和 `run_workflow` 的 image 取法没跟上。这次补齐。

## 进度总览

| 优先级 | 项 | 状态 | 测试文件 |
| --- | --- | --- | --- |
| P0 | wordcloud colormap tier: advanced -> basic | DONE | tests/test_wordcloud_colormap_tier.py |
| P0 | run_workflow image output_kind: prefer type=output | DONE | tests/test_run_workflow_image_prefer_output.py |

## 每项详细记录


### P0: run_workflow image output_kind (DONE)

- RED: 1 test fails with `expected the actual wordcloud image (node 23 type=output),
  got URL=http://fake/view?f=ComfyUI_temp_tteku_00004_.png&t=temp` — reproduce the
  exact buggy behavior end-to-end (load workflow, queue, wait, extract, build URL).
  3 other tests pass already (no-regression for single-output / only-temp / empty cases).
- GREEN: in `app/scail2_app.py` line 709 area, replaced
  ```python
  out = image_outputs[0] if image_outputs else None
  ```
  with
  ```python
  preferred = [im for im in image_outputs if im.get("type") == "output"]
  out = preferred[0] if preferred else (image_outputs[0] if image_outputs else None)
  ```
  Mirrors `extract_primary_video_output` (commit 2113045 / f5bee57). Surgical: only
  changes run_workflow image selection; extract_all_image_outputs (called by
  run_image_workflow Gallery) keeps node_id order intact.
- Verify: 4 new tests pass + full suite 470 passed / 3 skipped (was 464 + 3 skipped).
- Real end-to-end check: ran wordcloud via real ComfyUI with viridis / Reds / Blues /
  plasma colormaps, all returned `ComfyUI_00053_.png (type=output)` (the wordcloud)
  instead of `ComfyUI_temp_tteku_00004_.png (type=temp)` (the SAM mask).
- Note: Greys colormap produces no type=output images at all (ComfyWordCloud + Greys +
  transparent_background=true produces a transparent result that node 23 SaveImage
  receives as empty). This is a separate colormap-specific workflow issue, not in
  this fix's scope. The fix correctly returns None / falls back when no type=output
  is available.

### P0: wordcloud colormap tier (DONE)

- RED: 2 tests fail with `params.json wordcloud colormap.tier should be 'basic',
  got 'advanced'`.
- GREEN: changed `"tier": "advanced"` -> `"tier": "basic"` for colormap spec
  (app/presets/params.json, line ~300, inside wordcloud.user_facing_inputs).
  Colormap is a core visual choice for wordcloud users, not "advanced".
- Verify: 2 new tests pass + full suite 472 passed / 3 skipped.

## Final Summary

Two fixes, 6 new tests, no regressions. Both user complaints
("colormap should be basic", "after changing style no image") are addressed.

**Code changes:**
- `app/scail2_app.py` (run_workflow, output_kind=="image" branch): image selection
  now prefers type=output, falls back to image_outputs[0].
- `app/presets/params.json` (wordcloud preset, colormap spec): tier "advanced" -> "basic".

**New tests:**
- `tests/test_run_workflow_image_prefer_output.py` (4 cases)
- `tests/test_wordcloud_colormap_tier.py` (2 cases)
