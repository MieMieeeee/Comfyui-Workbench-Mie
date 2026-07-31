import json
from pathlib import Path

from app import config
from app.services import form_schema


def test_parse_sizes_supports_custom_and_rejects_malformed_entries():
    assert form_schema.parse_sizes(["768x512", "1200×800"]) == [(768, 512), (1200, 800)]
    assert form_schema.parse_sizes("768x") is None
    assert form_schema.parse_sizes(["768x512", "bad"]) is None


def test_ltx_t2v_uses_unified_image_sizes_schema():
    cfg = config.preset_config("ltx_23_t2v_distill")
    specs = cfg["user_facing_inputs"]
    size_specs = [s for s in specs if s.get("type") == "image_sizes"]
    assert len(size_specs) == 1
    assert size_specs[0]["node_id"] == "111"
    assert size_specs[0]["field"] == "sizes"
    assert not any(s.get("field") in ("width", "height") for s in specs)
    assert cfg["example"]["sizes"] == ["768x512"]


def test_size_presets_include_custom_size_metadata():
    cfg = config.preset_config("ltx_23_t2v_distill")
    spec = next(s for s in cfg["user_facing_inputs"] if s["type"] == "image_sizes")
    assert spec["allow_custom"] is True
    assert spec["min_width"] == 256
    assert spec["max_width"] == 1920

def test_runner_patches_video_size_from_image_sizes(monkeypatch):
    from app.services import runner
    captured = {}
    cfg = {
        "output_kind": "video",
        "user_facing_inputs": [
            {"node_id": "121", "field": "text", "type": "text", "default": "prompt"},
            {"node_id": "111", "field": "sizes", "type": "image_sizes", "default": ["768x512"], "min_width": 256, "max_width": 1920, "min_height": 256, "max_height": 1088},
        ],
        "fixed_patches": {},
    }
    monkeypatch.setattr(runner.config, "preset_config", lambda name: cfg)
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template", lambda name: {"111": {"inputs": {"width": 768, "height": 512}}})
    monkeypatch.setattr(runner.scail2_client, "patch_workflow", lambda wf, replacements, **kwargs: captured.update(replacements) or wf)
    monkeypatch.setattr(runner.scail2_client, "queue_prompt", lambda wf: ("pid", "cid"))
    monkeypatch.setattr(runner.scail2_client, "start_progress_listener", lambda cid: type("Q", (), {"put": lambda self, value: None})())
    monkeypatch.setattr(runner.scail2_client, "wait_for_completion", lambda *args, **kwargs: iter(["✅ done"]))
    monkeypatch.setattr(runner.scail2_client, "get_history", lambda pid: {})
    monkeypatch.setattr(runner.scail2_client, "extract_primary_video_output", lambda hist: None)
    monkeypatch.setattr(runner.history, "write_manifest", lambda manifest: None)
    list(runner.run_workflow("synthetic", "prompt", ["1025x513"]))
    assert captured["111"] == {"width": 1025, "height": 513, "batch_size": 1}


def test_all_image_presets_share_unified_size_display():
    """review 2026-07-27: 4 个 image preset (zimage/qwen/krea2/anima) 走全局 IMAGE_SIZE_PRESETS + allow_custom=True.

    统一显示: 5 个尺寸 + emoji label + 自定义 WxH 输入.
    保留细节: zimage / qwen 不加 min_width/max_width (用户要求不限制);
    ltx_23_t2v_distill 有限制 (不应被全局覆盖).
    """
    from app import config as _cfg
    for name in ("zimage", "qwen_image_2512_4step", "t2i_krea2", "Anima_turbo"):
        cfg = _cfg.preset_config(name)
        spec = next(s for s in cfg["user_facing_inputs"] if s["type"] == "image_sizes")
        # 全局注入: 5 个预设 + emoji label
        assert spec["presets"] == list(_cfg.IMAGE_SIZE_PRESETS),             f"{name} presets 应与全局 IMAGE_SIZE_PRESETS 一致"
        assert spec["allow_custom"] is True, f"{name} allow_custom 应为 True (全局默认)"

    # 限制不被全局覆盖: zimage / qwen 不写 bounds (用户要求不限制)
    for name in ("zimage", "qwen_image_2512_4step"):
        spec = next(s for s in config.preset_config(name)["user_facing_inputs"] if s["type"] == "image_sizes")
        for bound in ("min_width", "max_width", "min_height", "max_height"):
            assert bound not in spec, f"{name} 不应声明 {bound} (用户要求不限制)"

    # ltx_23_t2v_distill 自己写了 bounds, enrich 不覆盖
    ltx_spec = next(s for s in config.preset_config("ltx_23_t2v_distill")["user_facing_inputs"] if s["type"] == "image_sizes")
    assert ltx_spec["min_width"] == 256, "ltx spec 自己的 bounds 不应被全局覆盖"


def test_parse_sizes_accepts_single_wxh_string_for_runner_compat():
    """双数字框 UI 合成的 "WxH" 字符串放进 list 后, parse_sizes 必须能解出.

    锁数据模型: formValues[idx] 仍是 ["WxH", ...] 字符串数组 (UI 只是合成视图).
    runner / krea2 测试都依赖这个格式.
    """
    assert form_schema.parse_sizes(["999x666"]) == [(999, 666)]
    assert form_schema.parse_sizes(["1024x1024", "1280x720"]) == [(1024, 1024), (1280, 720)]


def test_image_runner_patches_custom_size_from_image_sizes(monkeypatch):
    """image 路径 (run_image_workflow) 也要吃自定义尺寸, patch 出 width/height/batch_size.

    当前 image 路径无 range 校验 (符合 zimage/qwen '不限制'); 这里只验证 patch 命中.
    """
    from app.services import runner
    captured = {}
    cfg = {
        "output_kind": "image",
        "user_facing_inputs": [
            {"node_id": "6", "field": "text", "type": "text", "default": "prompt"},
            {"node_id": "13", "field": "sizes", "type": "image_sizes",
             "default": ["1024x1024"], "allow_custom": True},
            {"node_id": "3", "field": "seed", "type": "int_random",
             "default": 0, "random_default": True},
        ],
        "fixed_patches": {},
    }
    monkeypatch.setattr(runner.config, "preset_config", lambda name: cfg)
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template",
                        lambda name: {"13": {"inputs": {"width": 1024, "height": 1024}}})
    monkeypatch.setattr(runner.scail2_client, "patch_workflow",
                        lambda wf, replacements, **kwargs: captured.update(replacements) or wf)
    monkeypatch.setattr(runner.scail2_client, "queue_prompt", lambda wf: ("pid", "cid"))
    monkeypatch.setattr(runner.scail2_client, "build_node_title_map", lambda wf: {})
    monkeypatch.setattr(runner.scail2_client, "start_progress_listener",
                        lambda cid: type("Q", (), {"put": lambda self, value: None})())
    monkeypatch.setattr(runner.scail2_client, "wait_for_completion",
                        lambda *args, **kwargs: iter(["✅ done in 00:01"]))
    monkeypatch.setattr(runner.scail2_client, "get_history", lambda pid: {})
    monkeypatch.setattr(runner.scail2_client, "extract_all_image_outputs", lambda hist: [])
    monkeypatch.setattr(runner.history, "write_manifest", lambda manifest: None)
    list(runner.run_image_workflow("synthetic", "prompt", ["999x666"], False, 77))
    assert captured["13"] == {"width": 999, "height": 666, "batch_size": 1}


def test_on_size_toggle_is_multi_select_not_single():
    """预设 checkbox 是多选: 勾第二个不丢掉第一个; 取消只移除自己.

    锁契约 (修复"勾 B 丢 A"的单选 bug):
      - formValues[idx] 是 ["WxH", ...] 字符串数组, runner image 路径按每个尺寸各跑一张
      - onSizeToggle 勾上: value 加入列表 (去重), 不替换
      - onSizeToggle 取消: 从列表移除该 value, 保留其它
      - 自定义尺寸项 (非预设) 不受预设 checkbox 影响
    """
    from pathlib import Path
    app_js = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
    # 必须有 "[...current, value]" 这种"追加"写法, 不能是 "[value, ...]" 这种"替换"写法
    assert "[...current, value]" in app_js
    # 取消时用 filter 移除单项, 不是清空
    on_toggle_start = app_js.index("onSizeToggle(event, presetName, specIdx) {")
    on_toggle_end = app_js.index("    },", on_toggle_start)
    on_toggle_body = app_js[on_toggle_start:on_toggle_end]
    assert "current.filter((item) => item !== value)" in on_toggle_body


def test_video_runner_uses_only_first_size(monkeypatch):
    """video 路径 (run_workflow) 只取尺寸列表第一个: 视频生成慢, 不做多尺寸循环.

    锁契约: 即使 UI 勾了多个尺寸, video runner 也只用 parsed[0].
    这跟 image 路径 (run_image_workflow 遍历所有尺寸跑多张) 不对称 ——
    是设计决策, 不是 bug.
    """
    from app.services import runner
    captured = {}
    cfg = {
        "output_kind": "video",
        "user_facing_inputs": [
            {"node_id": "121", "field": "text", "type": "text", "default": "prompt"},
            {"node_id": "111", "field": "sizes", "type": "image_sizes",
             "default": ["768x512"], "allow_custom": True,
             "min_width": 256, "max_width": 1920, "min_height": 256, "max_height": 1088},
        ],
        "fixed_patches": {},
    }
    monkeypatch.setattr(runner.config, "preset_config", lambda name: cfg)
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template",
                        lambda name: {"111": {"inputs": {"width": 768, "height": 512}}})
    monkeypatch.setattr(runner.scail2_client, "patch_workflow",
                        lambda wf, replacements, **kwargs: captured.update(replacements) or wf)
    monkeypatch.setattr(runner.scail2_client, "queue_prompt", lambda wf: ("pid", "cid"))
    monkeypatch.setattr(runner.scail2_client, "start_progress_listener",
                        lambda cid: type("Q", (), {"put": lambda self, value: None})())
    monkeypatch.setattr(runner.scail2_client, "wait_for_completion",
                        lambda *args, **kwargs: iter(["✅ done in 00:01"]))
    monkeypatch.setattr(runner.scail2_client, "get_history", lambda pid: {})
    monkeypatch.setattr(runner.scail2_client, "extract_primary_video_output", lambda hist: None)
    monkeypatch.setattr(runner.history, "write_manifest", lambda manifest: None)
    # 传 3 个尺寸, runner 只用第一个 768x512 (patch 出来 width=768)
    list(runner.run_workflow("synthetic", "prompt", ["768x512", "1024x576", "576x1024"]))
    assert captured["111"] == {"width": 768, "height": 512, "batch_size": 1}


def test_image_runner_multi_size_runs_all_segments(monkeypatch):
    """image 路径多尺寸: 每个尺寸各跑一段, 全部完成才结束.

    锁契约 (修复"多尺寸只跑第一张"的 bug):
      - run_image_workflow 传 N 个尺寸 -> queue_prompt 调 N 次
      - 单段完成 yield 用 🖼 前缀 (不是 ✅), 否则 stream_events 会把单段 ✅
        当成整个 run 成功而提前 break, 第二段永远不跑
      - 最后 yield 的 media 列表含 N 张图的 URL
    """
    from app.services import runner
    queue_count = {"n": 0}

    def fake_queue(wf):
        queue_count["n"] += 1
        return (f"pid{queue_count['n']}", "cid")

    def fake_history(pid):
        # 每段返回一张图, filename 跟 pid 末位绑定
        n = pid[-1]
        return {"outputs": {"1": {"images": [
            {"filename": f"img{n}.png", "subfolder": "", "type": "output"}]}}}

    cfg = {
        "output_kind": "image",
        "user_facing_inputs": [
            {"node_id": "6", "field": "text", "type": "text", "default": "p"},
            {"node_id": "13", "field": "sizes", "type": "image_sizes",
             "default": ["1024x1024"]},
            {"node_id": "3", "field": "seed", "type": "int_random",
             "default": 0, "random_default": True},
        ],
        "fixed_patches": {},
    }
    monkeypatch.setattr(runner.config, "preset_config", lambda name: cfg)
    monkeypatch.setattr(runner.scail2_client, "load_workflow_template",
                        lambda name: {"13": {"inputs": {"width": 1024, "height": 1024}}})
    monkeypatch.setattr(runner.scail2_client, "patch_workflow",
                        lambda wf, rep, **kw: wf)
    monkeypatch.setattr(runner.scail2_client, "queue_prompt", fake_queue)
    monkeypatch.setattr(runner.scail2_client, "build_node_title_map", lambda wf: {})
    monkeypatch.setattr(runner.scail2_client, "start_progress_listener",
                        lambda cid: type("Q", (), {"put": lambda self, value: None})())
    monkeypatch.setattr(runner.scail2_client, "wait_for_completion",
                        lambda *a, **kw: iter([f"📸 segment done"]))
    monkeypatch.setattr(runner.scail2_client, "get_history", fake_history)
    monkeypatch.setattr(runner.scail2_client, "extract_all_image_outputs",
                        lambda h: [v for node in h.get("outputs", {}).values()
                                   for v in node.get("images", [])])
    monkeypatch.setattr(runner.history, "write_manifest", lambda m: None)

    results = list(runner.run_image_workflow(
        "synthetic", "prompt", ["1024x1024", "1280x720"], False, 77))
    # 两段都跑了 (queue 2 次)
    assert queue_count["n"] == 2
    # 最后 yield 的 media 含 2 张图
    assert results[-1][0].startswith("✅")
    assert len(results[-1][1]) == 2
    # 关键契约: 除了最后的 "✅ 全部完成", 中间不能有"纯 ✅ 开头"的 yield
    # (会被 stream_events 的 _extract_status_kind startswith("✅") 判成 run 级 success,
    #  触发 break, 第二段永远不跑). 带 [idx/len] 前缀的 "[1/2] ✅ done" 不算 (不是纯 ✅ 开头).
    from app.services import status as status_svc
    pure_success_yields = [m for m, _ in results
                           if status_svc._extract_status_kind(m)[0] == "success"]
    # 只能有一个纯 success (最后的 "✅ 全部完成"), 不能有两个
    assert len(pure_success_yields) == 1, \
        f"多段 run 只能有一个 run 级 ✅, 实际: {pure_success_yields}"


def test_custom_size_card_has_checkbox_and_disabled_state():
    """自定义尺寸是一张带 checkbox 的卡片, 跟预设卡片视觉/交互对称.

    锁 UI 契约 (含 Alpine 响应式修法):
      - 自定义卡片 checkbox 用 x-model 双向绑 _custom_on (不是单向 :checked)
        —— 单向 :checked + @change 在 Alpine 3 下会被派生状态重置, 导致勾不上
      - _custom_on / _cw / _ch 三个辅助键必须经 _seedImageSizesCustomKeys
        在 initPanelScope + _applyFormValues 两条初始化路径都预建
        (Alpine 3 Proxy 不追踪后加的 key, 必须预建)
      - W/H 输入框 :disabled="!customChecked" — 未勾选时灰掉, 不能编辑
      - 改 W/H 走 onCustomSizeInput 实时同步 formValues[idx] (替换 custom 项)
    """
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    tmpl = (root / "app" / "templates" / "run.html").read_text(encoding="utf-8")
    app_js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    # 模板: checkbox 用 x-model 绑 _custom_on (双向, 不是单向 :checked)
    assert "x-model=\"formValues[idx + '_custom_on']\"" in tmpl
    assert ":disabled=\"!customChecked" in tmpl
    assert "custom-size-card" in tmpl
    # 不应再用单向 :checked 绑 customChecked (那是 bug 根因)
    assert ':checked="customChecked' not in tmpl
    # app.js: 三个辅助键 + 5 个 helper 必须存在 (review 2026-07-27, helper 提到 _seedImageSizesCustomKeys)
    assert "customChecked" in app_js
    assert "customW" in app_js
    assert "customH" in app_js
    assert "onCustomToggle" in app_js
    assert "onCustomSizeInput" in app_js
    assert "_seedImageSizesCustomKeys" in app_js, "辅助键预建必须走 helper, 不能内联"
    # 两条初始化路径都调 helper
    init_idx = app_js.index("async initPanelScope")
    apply_idx = app_js.index("_applyFormValues(panelEl, cfg, values)")
    init_section = app_js[init_idx:apply_idx]
    apply_section = app_js[apply_idx:init_idx + 10000]  # 取 _applyFormValues 函数体
    assert "_seedImageSizesCustomKeys" in init_section, "initPanelScope 必须调 _seedImageSizesCustomKeys"
    assert "_seedImageSizesCustomKeys" in apply_section, "_applyFormValues 必须调 _seedImageSizesCustomKeys"
    # 勾上时不设默认尺寸 —— 默认 1024x1024 会跟同名预设项串台, 让预设 checkbox 误亮.
    # onCustomToggle 里 W/H 空时不应硬塞 '1024', 应留空等用户输入.
    toggle_start = app_js.index("onCustomToggle(event, presetName, specIdx) {")
    toggle_end = app_js.index("    },", toggle_start)
    toggle_body = app_js[toggle_start:toggle_end]
    assert "|| '1024'" not in toggle_body, "勾上时不应默认 1024 (会跟预设串台)"
    assert "|| 1024" not in toggle_body, "勾上时不应默认 1024 (会跟预设串台)"


def test_custom_size_aux_keys_do_not_leak_to_runner():
    """辅助键 (_custom_on/_cw/_ch) 仅用于 Alpine 双向绑定, 不进 collectFormValues.

    锁: collectFormValues 只对 int_random 跳过 2 格, 其它 spec 都按 flatIdx 推 1 格 ——
    自定义 W/H 是 formValues[idx] 主数组里的 "WxH" 字符串, 不是独立 form value.
    """
    from pathlib import Path
    app_js = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
    # collectFormValues 里 int_random 是唯一跳 2 的分支, 没有 image_sizes 特判
    assert "spec.type === 'int_random'" in app_js
    # 辅助键不应出现在 collectFormValues 函数体里
    collect_start = app_js.index("collectFormValues(panel) {")
    collect_end = app_js.index("    },", collect_start)
    collect_body = app_js[collect_start:collect_end]
    for aux in ("_custom_on", "_cw", "_ch"):
        assert aux not in collect_body, f"{aux} 不应泄漏进 collectFormValues (会污染 runner 入参)"
