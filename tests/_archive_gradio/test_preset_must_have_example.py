"""项目规矩：每个 preset 的 `example` 是它的默认参数, 也是 UI 上第一眼看到的。

约定 (review 2026-07-11):
  - demo.load 触发 _auto_load_example(default_wf) -> default preset 表单填 example
  - wf_radio.change 触发 _auto_load_example(name) -> 首次切到 preset 填 example
  - 已有 preset (zimage / sca12_motion / sca12_replace) 都遵循这条
  - 新加 preset 必须填 example, 这是契约

测试覆盖:
  - 所有 preset 都有 example 字段 (非空)
  - example 至少覆盖一个 user_facing_inputs 字段
  - example_to_form_values(preset) 不抛异常
  - 重新跑一遍 example_to_form_values 不会改变 _AUTO_LOADED (用 default 行为)
  - UI 启动时 demo.load 的 lambda 能直接调 (不依赖外部 IO)
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest
from app import config, scail2_app


# --- 1) 所有 preset 都有非空 example ---

def test_every_preset_has_non_empty_example():
    """所有 preset 必须在 params.json 里填 example 字段, 不能空.

    这是 UI 启动时表单默认填 example 的契约 -- 没有 example 就启动后看到空表单.
    """
    workflows = config.list_workflows()
    missing = []
    for wf in workflows:
        cfg = config.preset_config(wf["name"])
        ex = cfg.get("example")
        if not ex or not isinstance(ex, dict) or len(ex) == 0:
            missing.append(wf["name"])
    assert not missing, (
        f"以下 preset 缺 example 字段: {missing}. "
        f"UI 启动时会拿不到默认参数, 表单空着. "
        f"在 params.json 的 preset 配置里加 example 块 (参照 zimage / sca12_motion)."
    )


# --- 2) example 至少覆盖一个 user_facing_inputs 字段 ---

def test_every_preset_example_covers_at_least_one_user_facing_input():
    """example 必须至少覆盖一个 user_facing_inputs 字段, 否则自动填没意义.

    弱检查: example 里的 key (reference_image / drive_video / ref_prompt / drive_prompt /
    main_prompt / segments / prompt / sizes / frame_load_cap / seed) 至少要有一个.
    """
    KEYS = {
        "reference_image", "drive_video", "ref_prompt", "drive_prompt",
        "main_prompt", "segments", "prompt", "sizes", "frame_load_cap", "seed",
    }
    workflows = config.list_workflows()
    for wf in workflows:
        cfg = config.preset_config(wf["name"])
        ex = cfg.get("example") or {}
        covered = KEYS.intersection(ex.keys())
        assert covered, (
            f"{wf['name']}: example 至少要覆盖一个 user_facing_inputs key "
            f"({sorted(KEYS)}), 当前 example 实际是 {ex!r}"
        )


# --- 3) example_to_form_values 对每个 preset 都能跑通 ---

def test_example_to_form_values_runs_for_every_preset():
    """example_to_form_values(preset) 必须能跑通 (文件可能不在, 但函数不抛)."""
    for wf in config.list_workflows():
        # 不抛即过
        vals = scail2_app.example_to_form_values(wf["name"])
        # 用 flat components 数量 (int_random 拆 2 个, 其它 1 个)
        import gradio as gr
        with gr.Blocks():
            flat = scail2_app._render_workflow_form(wf["name"])
        assert len(vals) == len(flat), (
            f"{wf['name']}: example_to_form_values 返回 {len(vals)} 个值, "
            f"但 flat components 有 {len(flat)} 个. "
            f"int_random 拆 2 个, 其它 1 个; spec 数和 components 数不一定相等."
        )


# --- 4) auto-load example 不污染 _AUTO_LOADED (除了 active preset) ---

def test_auto_load_example_marks_active_preset_only():
    """_resolve_auto_load_updates 调一次后, 只把 active preset 加入 _AUTO_LOADED.
    验证 default 行为契约: 切到 preset -> 加入 -> 切到另一个 -> 两个都在集合里.
    """
    scail2_app._AUTO_LOADED.clear()
    # 模拟 demo.load
    workflows = config.list_workflows()
    first = workflows[0]["name"]
    second = workflows[1]["name"] if len(workflows) >= 2 else None

    # 构造一个 minimal preset_inputs_map
    import gradio as gr
    pmap = {}
    with gr.Blocks():
        for wf in workflows:
            pmap[wf["name"]] = scail2_app._render_workflow_form(wf["name"])
    scail2_app._resolve_auto_load_updates(pmap, first)
    assert first in scail2_app._AUTO_LOADED
    if second:
        assert second not in scail2_app._AUTO_LOADED, (
            f"调 _resolve_auto_load_updates({first!r}) 不应把 {second!r} 加入 _AUTO_LOADED"
        )
    # 清理
    scail2_app._AUTO_LOADED.clear()


# --- 5) demo.load 的 lambda 不抛 (模拟启动) ---

def test_demo_load_lambda_runs_without_error():
    """build_ui 里的 demo.load(lambda: _auto_load_example(default_wf)) 必须能直接调.
    验证 lambda body 在生产环境 (无外部 IO) 下能跑, 不抛异常.

    注: 实际 demo.load 由 Gradio 框架在 SPA 启动时调, 这里用 lambda 直接调模拟.
    """
    scail2_app._AUTO_LOADED.clear()
    workflows = config.list_workflows()
    default_wf = workflows[0]["name"]
    import gradio as gr
    pmap = {}
    with gr.Blocks():
        for wf in workflows:
            pmap[wf["name"]] = scail2_app._render_workflow_form(wf["name"])
    # 模拟 demo.load 的 lambda
    result = scail2_app._resolve_auto_load_updates(pmap, default_wf)
    # 必须返回 list, 长度对齐 total inputs
    total = sum(len(pmap[wf["name"]]) for wf in workflows)
    assert isinstance(result, list)
    assert len(result) == total
    # default preset 应被标记
    assert default_wf in scail2_app._AUTO_LOADED
    scail2_app._AUTO_LOADED.clear()




# ---- output_box 默认填 example (review 2026-07-11) ----

def test_output_box_initial_value_is_example_preview():
    """output_box (生成结果) 初始值应是 example.preview_image / preview_video 渲染出来的 HTML,
    不是 '运行后这里显示结果' 占位符.

    设计: 默认参数 = example, 用户打开工作流后第一眼看到 example 跑出来的效果.
    跑了之后 _run_and_format 会用实际生成结果覆盖这个默认值.
    """
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("zimage")
    output_boxes = [
        b for b in demo.blocks.values()
        if isinstance(b, gr.HTML) and "result-area" in (getattr(b, "elem_classes", None) or [])
    ]
    assert len(output_boxes) == 1, f"zimage 应只有 1 个 result-area, 实际 {len(output_boxes)}"
    val = output_boxes[0].value or ""
    assert "\u8fd0\u884c\u540e\u8fd9\u91cc\u663e\u793a\u7ed3\u679c" not in val, (
        f"output_box 初始值不应再是占位符 '运行后这里显示结果', 实际:\n{val[:300]}"
    )
    assert "result-area-default" in val, (
        f"output_box 初始值应含 result-area-default class 标记示例默认状态:\n{val[:300]}"
    )
    # 应包含 zimage 示例图 (用 /gradio_api/file= 路由, 浏览器可访问)
    assert "/gradio_api/file=app/static/examples/zimage_720x1280_0001.png" in val, (
        f"output_box 应通过 /gradio_api/file= 路由引用 zimage 示例图, 实际:\n{val[:300]}"
    )


def test_output_box_uses_preview_video_for_sca12_presets():
    """sca12_motion / sca12_replace 有 preview_video, output_box 应渲染 <video> 标签,
    视频源用 /gradio_api/file= 路由."""
    import gradio as gr
    for preset_name in ("sca12_motion", "sca12_replace"):
        with gr.Blocks() as demo:
            scail2_app._render_workflow_form(preset_name)
        output_boxes = [
            b for b in demo.blocks.values()
            if isinstance(b, gr.HTML) and "result-area" in (getattr(b, "elem_classes", None) or [])
        ]
        assert len(output_boxes) == 1
        val = output_boxes[0].value or ""
        assert "<video" in val, f"{preset_name}: 应渲染 <video> 标签, 实际:\n{val[:300]}"
        # 视频文件应通过 /gradio_api/file= 路由引用
        assert f"/gradio_api/file=app/static/examples/{preset_name}_3seg.mp4" in val, (
            f"{preset_name}: 应通过 /gradio_api/file= 路由引用 {preset_name}_3seg.mp4, 实际:\n{val[:300]}"
        )
        # caption 标记示例状态
        assert "\u793a\u4f8b\u6548\u679c" in val, (
            f"{preset_name}: 应有 '示例效果' caption 提示这是默认状态"
        )


def test_output_box_uses_file_route_not_local_path():
    """output_box 里的 src 必须是 /gradio_api/file=... URL, 不能是本地路径 (F:\\...).

    bug 故事: 之前 _resolve_preview_path 返回 str(config.REPO_ROOT / rel) 形式的本地路径,
    <img src='F:\\...'> 被浏览器当相对 URL 解析, 找不到图片 -> 截图里只看到破图标 + caption.
    改成返回 /gradio_api/file=... 路由后浏览器能正常加载 (Gradio 6 路由是 /gradio_api/file=, 不是裸 /file=).
    """
    import gradio as gr
    for preset_name in ("zimage", "sca12_motion", "sca12_replace"):
        with gr.Blocks() as demo:
            scail2_app._render_workflow_form(preset_name)
        output_boxes = [
            b for b in demo.blocks.values()
            if isinstance(b, gr.HTML) and "result-area" in (getattr(b, "elem_classes", None) or [])
        ]
        val = output_boxes[0].value or ""
        # 不能是 Windows 绝对路径
        assert not any(d + ":" in val for d in "CDEFGHIJKLMNOPQRSTUVWXYZ"), (
            f"{preset_name}: src 包含 Windows 盘符, 应该是 /gradio_api/file= URL, 实际:\n{val[:300]}"
        )
        # 必须是 /gradio_api/file= 路由
        assert "src='/gradio_api/file=" in val, (
            f"{preset_name}: src 必须是 /gradio_api/file=... 形式, 实际:\n{val[:300]}"
        )


def test_output_box_caption_mentions_default_params():
    """output_box 的 示例效果 caption 应明确说明 '默认参数对应的结果', 用户能分清示例与实际运行结果.

    跑了之后这个 caption 会被覆盖, 不会干扰实际输出的阅读.
    """
    import gradio as gr
    with gr.Blocks() as demo:
        scail2_app._render_workflow_form("zimage")
    output_boxes = [
        b for b in demo.blocks.values()
        if isinstance(b, gr.HTML) and "result-area" in (getattr(b, "elem_classes", None) or [])
    ]
    val = output_boxes[0].value or ""
    assert "\u9ed8\u8ba4\u53c2\u6570\u5bf9\u5e94\u7684\u7ed3\u679c" in val, (
        f"caption 应明确说明 '默认参数对应的结果', 实际:\n{val}"
    )

# --- Restart-safe example defaults and cache-safe preview URLs ---


def _normalized_component_value(component):
    value = component.value
    if isinstance(value, dict) and "orig_name" in value:
        return Path(value["orig_name"]).name
    if getattr(value, "orig_name", None):
        return Path(value.orig_name).name
    return value


def _normalized_expected_value(component, value):
    import gradio as gr
    if isinstance(component, gr.File) and value:
        return Path(value).name
    return value


def test_rendered_form_initial_values_match_example_for_every_preset():
    """Fresh server/session must render example values without load/change events."""
    import gradio as gr

    failures = []
    for wf in config.list_workflows():
        preset_name = wf["name"]
        expected = scail2_app.example_to_form_values(preset_name)
        with gr.Blocks():
            components = scail2_app._render_workflow_form(preset_name)
        assert len(components) == len(expected)
        for index, (component, expected_value) in enumerate(zip(components, expected)):
            actual = _normalized_component_value(component)
            wanted = _normalized_expected_value(component, expected_value)
            if actual != wanted:
                failures.append((preset_name, index, getattr(component, "label", ""), actual, wanted))

    assert not failures, (
        "Fresh render did not start from preset.example values:\n"
        + "\n".join(
            f"  {name}[{index}] {label!r}: actual={actual!r}, expected={wanted!r}"
            for name, index, label, actual, wanted in failures
        )
    )


def test_every_local_example_preview_url_contains_current_content_hash():
    """Replacing a preview at the same path must produce a new browser URL."""
    import gradio as gr

    for wf in config.list_workflows():
        preset_name = wf["name"]
        cfg = config.preset_config(preset_name)
        example = cfg["example"]
        raw = next(
            (example.get(key) for key in ("preview_video", "preview_image", "preview_audio") if example.get(key)),
            None,
        )
        assert raw, f"{preset_name}: example has no preview"
        if str(raw).startswith(("http://", "https://")):
            continue
        preview_path = Path(raw)
        if not preview_path.is_absolute():
            preview_path = config.REPO_ROOT / preview_path
        digest = hashlib.sha256(preview_path.read_bytes()).hexdigest()[:16]

        with gr.Blocks() as demo:
            scail2_app._render_workflow_form(preset_name)
        output = next(
            block for block in demo.blocks.values()
            if isinstance(block, gr.HTML)
            and "result-area" in (getattr(block, "elem_classes", None) or [])
        )
        html = output.value or ""
        assert f"?v={digest}" in html, (
            f"{preset_name}: preview URL must include current content hash {digest}; HTML={html[:300]!r}"
        )

def _example_contract_digest(example: dict) -> str:
    """Hash default parameters plus every configured input/output example asset."""
    file_keys = (
        "reference_image", "drive_video", "preview_image", "preview_video", "preview_audio"
    )
    params = {
        key: value
        for key, value in example.items()
        if key not in file_keys and key != "contract_sha256"
    }
    digest = hashlib.sha256(
        json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    for key in file_keys:
        raw = example.get(key)
        if not raw:
            continue
        digest.update(key.encode("ascii"))
        if str(raw).startswith(("http://", "https://")):
            digest.update(str(raw).encode("utf-8"))
            continue
        path = Path(raw)
        if not path.is_absolute():
            repo_path = config.REPO_ROOT / path
            path = repo_path if repo_path.exists() else Path(scail2_app._resolve_example_file(raw))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_every_example_contract_matches_current_params_and_assets():
    """Changing a prompt or asset requires regenerating and resigning that example pair."""
    failures = []
    for wf in config.list_workflows():
        preset_name = wf["name"]
        example = config.preset_config(preset_name)["example"]
        actual = _example_contract_digest(example)
        expected = example.get("contract_sha256")
        if actual != expected:
            failures.append((preset_name, expected, actual))
    assert not failures, (
        "Example prompt/input/output contracts are stale:\n"
        + "\n".join(
            f"  {name}: configured={expected!r}, current={actual}"
            for name, expected, actual in failures
        )
    )

def test_every_basic_text_input_is_explicitly_backed_by_example():
    """A visible prompt must resolve to an example key, never an unrelated spec default.

    契约 (review 2026-07-14):
      - prompt_pool 类型固定走 example["prompt"]
      - text 类型必须显式声明 spec["example_key"], 不再允许靠 node_id 隐式兜底
        (旧的 special_keys = {"362":..., "348":..., "360":...} 机制已下线,
         sca12 的 text spec 现在在 params.json 里显式写 example_key)
    """
    failures = []
    for wf in config.list_workflows():
        preset_name = wf["name"]
        cfg = config.preset_config(preset_name)
        example = cfg["example"]
        for spec in cfg["user_facing_inputs"]:
            if spec.get("tier", "basic") != "basic" or spec["type"] not in ("text", "prompt_pool"):
                continue
            if spec["type"] == "prompt_pool":
                example_key = "prompt"
            else:
                example_key = spec.get("example_key")
                if not example_key:
                    failures.append((preset_name, spec["label"], "<missing example_key>"))
                    continue
            if example_key not in example:
                failures.append((preset_name, spec["label"], example_key))
    assert not failures, (
        "Visible text inputs without an explicit preset.example value:\n"
        + "\n".join(
            f"  {name}: {label!r} expects example[{key!r}]"
            for name, label, key in failures
        )
    )


def test_versioned_preview_url_changes_when_same_path_bytes_change(tmp_path, monkeypatch):
    """A browser must receive a different URL after an in-place preview replacement."""
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    preview = tmp_path / "app" / "static" / "examples" / "preview.mp4"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"old-preview")
    old_url = scail2_app._versioned_preview_url(preview)
    preview.write_bytes(b"new-preview")
    new_url = scail2_app._versioned_preview_url(preview)
    assert old_url != new_url
    assert old_url.startswith("/gradio_api/file=app/static/examples/preview.mp4?v=")
    assert new_url.startswith("/gradio_api/file=app/static/examples/preview.mp4?v=")
