"""UI helper 单元测试：last_run 持久化、category icon、media HTML 渲染、status text。

这些 helper 都是上轮 UI 重构新增的，独立于 build_ui 测试，能跑得更快、
定位更准。e2e 渲染测试见 tests/test_e2e_render.py。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import config, scail2_app


# ---- _save_last_run / _load_last_run round-trip ----

def test_last_run_save_and_load_roundtrip(tmp_path, monkeypatch):
    """写一组混合类型值，再读回，列表对齐 + 内容相等。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    values = [None, "hello world", 42, 3.14, True, [1, 2, "x"], {"k": "v"}, "/some/path.png"]
    scail2_app._save_last_run("sca12_replace", values)

    out = scail2_app._load_last_run("sca12_replace", len(values))
    assert out == values


def test_load_last_run_missing_returns_all_none(tmp_path, monkeypatch):
    """没写过这个 preset -> 全 None。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    out = scail2_app._load_last_run("never_saved_preset", 5)
    assert out == [None] * 5


def test_load_last_run_pads_when_too_short(tmp_path, monkeypatch):
    """存的列表比当前 n_inputs 短 -> 后补 None。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    (tmp_path / "short.json").write_text(json.dumps([1, 2]), encoding="utf-8")
    out = scail2_app._load_last_run("short", 5)
    assert out == [1, 2, None, None, None]


def test_load_last_run_truncates_when_too_long(tmp_path, monkeypatch):
    """存的列表比当前 n_inputs 长 -> 截断。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    (tmp_path / "long.json").write_text(json.dumps([1, 2, 3, 4, 5]), encoding="utf-8")
    out = scail2_app._load_last_run("long", 3)
    assert out == [1, 2, 3]


def test_load_last_run_corrupt_returns_none(tmp_path, monkeypatch):
    """文件存在但 JSON 烂掉 -> 不崩，全 None。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    out = scail2_app._load_last_run("broken", 3)
    assert out == [None, None, None]


def test_load_last_run_non_list_returns_none(tmp_path, monkeypatch):
    """存的不是 list -> 全 None（防 schema 漂移）。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    (tmp_path / "dict.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    out = scail2_app._load_last_run("dict", 3)
    assert out == [None, None, None]


def test_save_last_run_serializes_unknown_object(tmp_path, monkeypatch):
    """遇到 gr.File 之类的非原生对象 -> str(v) 兜底，不崩。"""
    monkeypatch.setattr(config, "LAST_RUN_DIR", tmp_path)
    weird = MagicMock()
    weird.__str__ = lambda self: "<MagicMock>"
    scail2_app._save_last_run("weird", [weird])
    out = scail2_app._load_last_run("weird", 1)
    assert out == ["<MagicMock>"]


# ---- _category_icon ----

def test_category_icon_known_categories():
    assert scail2_app._category_icon("video") == chr(0x1F3AC)
    assert scail2_app._category_icon("image") == chr(0x1F5BC) + chr(0xFE0F)
    assert scail2_app._category_icon("audio") == chr(0x1F50A)
    assert scail2_app._category_icon("3d") == chr(0x1F9CA)
    assert scail2_app._category_icon("other") == chr(0x1F4E6)


def test_category_icon_unknown_falls_back_to_other():
    """未知 category 不能返回空串，要兜底成 📦。"""
    icon = scail2_app._category_icon("never_heard_of_it")
    assert icon == chr(0x1F4E6)


# ---- _media_to_html ----

def test_media_to_html_none_returns_placeholder():
    out = scail2_app._media_to_html(None, is_image=True)
    assert "等待结果" in out
    assert "padding" in out


def test_media_to_html_empty_image_list_returns_placeholder():
    out = scail2_app._media_to_html([], is_image=True)
    assert "等待结果" in out


def test_media_to_html_single_image_url():
    out = scail2_app._media_to_html("http://x/y.png", is_image=True)
    assert "<img" in out
    assert "y.png" in out
    assert "max-width:100%" in out


def test_media_to_html_image_list_grid():
    urls = ["http://x/a.png", "http://x/b.png", "http://x/c.png"]
    out = scail2_app._media_to_html(urls, is_image=True)
    # 3 张图，每张都有 <img
    assert out.count("<img") == 3
    # 每张都用网格宽度 32%
    assert out.count("max-width:32%") == 3


def test_media_to_html_video_url_uses_video_tag():
    out = scail2_app._media_to_html("http://x/clip.mp4", is_image=False)
    assert "<video" in out
    assert "controls" in out
    assert "clip.mp4" in out


def test_media_to_html_unknown_http_url_falls_back_to_banner():
    """不在 image/video 扩展名里的 URL -> .file-fallback banner。"""
    out = scail2_app._media_to_html("http://x/output.glb", is_image=False)
    assert "file-fallback" in out
    assert "output.glb" in out or "未知" in out


def test_media_to_html_image_extension_video_context_still_image():
    """is_image=False 但 URL 是图片扩展名 -> 仍走 <img>，不会被当视频。"""
    out = scail2_app._media_to_html("http://x/a.png", is_image=False)
    assert "<img" in out
    assert "<video" not in out


def test_media_to_html_empty_src_returns_placeholder():
    out = scail2_app._media_to_html([""], is_image=False)
    assert "等待结果" in out


# ---- _comfy_status_text ----

def test_comfy_status_text_ok_green_dot():
    with patch("app.scail2_client.check_connection", return_value=(True, "ok")), \
         patch("app.scail2_client.get_base_url", return_value="http://127.0.0.1:8188"):
        text = scail2_app._comfy_status_text()
    assert chr(0x1F7E2) in text
    assert "127.0.0.1:8188" in text


def test_comfy_status_text_down_red_dot():
    with patch("app.scail2_client.check_connection", return_value=(False, "no")), \
         patch("app.scail2_client.get_base_url", return_value="http://127.0.0.1:8188"):
        text = scail2_app._comfy_status_text()
    assert chr(0x1F534) in text
    assert "127.0.0.1:8188" in text


def test_comfy_status_text_handles_exception():
    """check_connection 抛异常时不能崩，应该走红点分支。"""
    with patch("app.scail2_client.check_connection", side_effect=RuntimeError("boom")), \
         patch("app.scail2_client.get_base_url", return_value="http://x"):
        text = scail2_app._comfy_status_text()
    assert chr(0x1F534) in text


# ---- _open_output_dir_action ----

def test_open_output_dir_action_creates_dir_and_returns_status(monkeypatch, tmp_path):
    """点 📂 -> 创建目录 + 调 Popen（不实际打开系统文件管理器）+ 返回状态文字。"""
    monkeypatch.setattr(config, "COMFY_OUTPUT_DIR", tmp_path / "outputs")
    fake_popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    # 仅在 windows 上要 explorer；跨平台 Popen 路径不同，这里统一 patch 掉。
    msg = scail2_app._open_output_dir_action()
    assert (tmp_path / "outputs").exists()
    # 返回文案是 "已打开: {path}"
    assert "已打开" in msg
    assert "outputs" in msg
    # Popen 至少被调一次（参数因平台而异，不细校验）
    assert fake_popen.called


# ---- _render_workflow_form has_expected_state_buttons ----

def test_render_workflow_form_creates_load_last_btn_per_preset():
    """每个 preset 都应有一个 '📂 加载上次成功参数' 按钮（不一定 visible，取决于 has_last_run）。"""
    import gradio as gr
    from app import config as cfg
    workflows = cfg.list_workflows()
    assert workflows, "需要至少一个 preset"
    for w in workflows:
        with gr.Blocks() as demo:
            scail2_app._render_workflow_form(w["name"])
        labels = [str(getattr(b, "value", "") or "") for b in demo.blocks.values()]
        # 按钮 label 写在 gr.Button(value=...)
        any_last_btn = any("加载上次成功参数" in lbl for lbl in labels)
        assert any_last_btn, f"{w['name']} 缺少 '📂 加载上次成功参数' 按钮"


def test_render_workflow_form_creates_status_accordion():
    """📜 运行日志 Accordion 每个 preset 都要有（advanced 折叠区可以有，但这个不能少）。"""
    import gradio as gr
    from app import config as cfg
    workflows = cfg.list_workflows()
    for w in workflows:
        with gr.Blocks() as demo:
            scail2_app._render_workflow_form(w["name"])
        # Accordion 的 label 在 .label 字段
        accordion_labels = [str(getattr(b, "label", "") or "") for b in demo.blocks.values()
                            if isinstance(b, gr.Accordion)]
        assert any("运行日志" in lbl for lbl in accordion_labels), \
            f"{w['name']} 缺 '📜 运行日志' Accordion"

# ---- _yield_run_stream: 收尾 yield 保留最后生成的 media ----

def test_yield_run_stream_final_yield_preserves_image():
    """Regression: run_fn yield 完 image 后,helper 的最后一次 yield
    必须把 image HTML 喂给 output_box,不能重置成 None 占位。

    复现用户报告:跑完 zimage 后,运行日志显示 ✅ 全部完成,共 1 张图”
    但右侧“生成结果”区卡在“等待结果…”占位,看不到图。
    """
    from app import scail2_app
    fake_url = "http://127.0.0.1:8188/view?f=z_00001_.png"

    def fake_run(preset_name, *vals):
        yield "[READY] preparing...", None
        yield "⏳ 准备生成 1 张图...", None
        yield "⏳ [1/1] 1024x1024 seed=12345...", []
        yield "[1/1] ⏳ 00:00 waiting for aabbccdd...", []
        yield "[1/1] ✅ done in 00:12", []
        yield "✅ [1/1] 1024x1024 done", [fake_url]
        yield "✅ 全部完成，共 1 张图", [fake_url]

    yields = list(scail2_app._yield_run_stream(fake_run, "zimage", (), is_image=True))
    assert len(yields) >= 2, "helper should yield at least once per run_fn yield + final"
    last = yields[-1]
    # 6-tuple: (status_text, media_html, error_update, re_run_visible_update, open_dir_msg_update, last_media)
    assert len(last) == 6
    status_text, media_html, _eu, _ru, _ou, last_media = last
    # 最终 yield 必须是 image HTML(不能是 “等待结果...”占位)
    assert "等待结果" not in media_html, (
        f"final yield clobbered the generated image with placeholder; got {media_html!r}"
    )
    assert "<img" in media_html and fake_url in media_html
    # last_media 字段也保留 URL list(供调用方做收尾 yield)
    assert last_media == [fake_url]


def test_yield_run_stream_final_yield_preserves_video():
    """视频 preset 的等价回归:SCAIL2 等 video workflow 的最后输出不被覆盖。"""
    from app import scail2_app
    fake_url = "http://127.0.0.1:8188/view?f=clip_00001.mp4"

    def fake_run(preset_name, *vals):
        yield "[READY] preparing...", None
        yield "⏳ [4/5] waiting for ComfyUI...", None
        yield "✅ done in 00:45", fake_url

    yields = list(scail2_app._yield_run_stream(fake_run, "sca12_replace", ("ref",), is_image=False))
    last = yields[-1]
    status_text, media_html, _eu, _ru, _ou, last_media = last
    assert "等待结果" not in media_html, (
        f"final yield clobbered the generated video; got {media_html!r}"
    )
    assert "<video" in media_html and fake_url in media_html
    assert last_media == fake_url


def test_yield_run_stream_no_media_yields_placeholder():
    """run_fn 全程没 yield 过非空 media → 收尾 yield 仍走"等待结果…"占位。"""
    from app import scail2_app

    def fake_run(preset_name, *vals):
        yield "[READY] preparing...", None
        yield "❌ queue: not connected", None

    yields = list(scail2_app._yield_run_stream(fake_run, "zimage", (), is_image=True))
    last = yields[-1]
    status_text, media_html, err_upd, _ru, _ou, last_media = last
    assert "等待结果" in media_html
    assert last_media is None
    # 错误 banner 在 ❌ 那一次 yield 应可见
    # (收尾 yield 会清掉 banner，避免错误状态占据界面)
    any_err_visible = any(y[2].get("visible") is True for y in yields)
    assert any_err_visible, "expected at least one yield with err_upd visible=True"
    # 最后一次 yield (收尾) 会清掉 banner
    assert last[2].get("visible") is False


def test_yield_run_stream_exception_preserves_last_media():
    """run_fn 中途抛异常 → 异常分支 yield 仍保留之前生成的图/视频。"""
    from app import scail2_app
    fake_url = "http://127.0.0.1:8188/view?f=z_00001_.png"

    def fake_run(preset_name, *vals):
        yield "[READY] preparing...", None
        yield "✅ [1/2] done", [fake_url]
        raise RuntimeError("simulated network drop")

    yields = list(scail2_app._yield_run_stream(fake_run, "zimage", (), is_image=True))
    # 最后两个 yield:异常分支 + 收尾,都不应覆盖之前的图
    last = yields[-1]
    penultimate = yields[-2]
    _, last_media_html, _, _, _, _ = last
    _, pen_media_html, _, _, _, _ = penultimate
    assert fake_url in last_media_html, f"final yield lost image: {last_media_html!r}"
    assert fake_url in pen_media_html, f"exception yield lost image: {pen_media_html!r}"


def test_yield_run_stream_calls_on_status_done_on_check():
    """run_fn yield ✅ 时,on_status_done 回调被调用(vals 透传)。"""
    from app import scail2_app

    calls: list[tuple[str, tuple]] = []

    def on_done(status_msg, vals):
        calls.append((status_msg, vals))

    def fake_run(preset_name, *vals):
        yield "⏳ preparing...", None
        yield "✅ done", None

    vals_in = ("prompt-text", ["1024x1024"], 0)
    list(scail2_app._yield_run_stream(fake_run, "zimage", vals_in, is_image=True, on_status_done=on_done))
    assert any(s.startswith("✅") for s, _ in calls), f"on_status_done not called: {calls!r}"
    # vals 透传
    _, last_vals = calls[-1]
    assert last_vals == vals_in



# ---- closure-level: 验证 _run_and_format 闭包本身接对 helper ----


def _get_run_and_format_fn(preset_name, fake_run_fn):
    _DOC = ("渲染 form 并从 Gradio Blocks 里抓 _run_and_format 闭包。\n\n"

            "必须把 fake_run_fn patch 到 scail2_app 上 *before* _render_workflow_form,\n"

            "这样 closure 在 run_fn = run_image_workflow ... 这一行捕获的就是 fake。")
    import gradio as gr
    from unittest.mock import patch
    from app import scail2_app

    is_image = preset_name == "zimage"
    attr = "run_image_workflow" if is_image else "run_workflow"

    with patch(f"app.scail2_app.{attr}", fake_run_fn), \
         patch("app.scail2_app._save_last_run"), \
         gr.Blocks() as demo:
        scail2_app._render_workflow_form(preset_name)

    for entry in demo.fns.values():
        if getattr(entry.fn, "__name__", "") == "_run_and_format":
            return entry.fn
    raise AssertionError("_run_and_format not found in demo.fns")


def test_run_and_format_closure_final_yield_preserves_zimage():
    """Regression (closure-level): zimage 跑完后,_run_and_format 的最后一次
    yield 仍要把 image HTML 喂给 output_box,不能重置成等待结果占位。

    这个测试和 _yield_run_stream 的单测区别在于:它走的是真实的
    _run_and_format 闭包代码路径,能抓住以下单测抓不到的回归:
      - 有人把 wrapper 删了,直接 inline 旧的 buggy 逻辑(单测照样过)
      - 有人改了 wrapper 让它不调 _yield_run_stream(单测照样过)
      - 有人改了 wrapper 的最终 yield 把 media 重置成 None(单测照样过)
    """
    fake_url = "http://127.0.0.1:8188/view?f=z_00001_.png"

    def fake_run_image(preset_name, *vals):
        yield "[READY] preparing image gen...", None
        yield chr(0x23F3) + " 准备生成 1 张图...", None
        yield chr(0x23F3) + " [1/1] 1024x1024 seed=12345...", []
        yield "[1/1] " + chr(0x23F3) + " 00:00 waiting for pid-fake...", []
        yield "[1/1] " + chr(0x2705) + " done in 00:12", []
        yield chr(0x2705) + " [1/1] 1024x1024 done", [fake_url]
        yield chr(0x2705) + " 全部完成，共 1 张图", [fake_url]

    target_fn = _get_run_and_format_fn("zimage", fake_run_image)
    yields = list(target_fn("a prompt", ["1024x1024"], 0))

    last = yields[-1]
    status_text, media_html, err_upd, re_run_upd, open_dir_upd, btn_upd, status_bar_upd = last
    assert chr(0x7B49) not in media_html, (
        f"BUG: 闭包收尾 yield 把刚生成的图覆盖成等待结果占位; got media_html={media_html!r}"
    )
    assert "<img" in media_html and fake_url in media_html, (
        f"BUG: 闭包收尾 yield 缺少 image; got media_html={media_html!r}"
    )


def test_run_and_format_closure_final_yield_preserves_video():
    """SCAIL2 视频 preset 的等价 closure-level 回归。"""
    fake_url = "http://127.0.0.1:8188/view?f=clip_00001.mp4"

    def fake_run_video(preset_name, *vals):
        yield "[READY] preparing...", None
        yield chr(0x23F3) + " [4/5] waiting for ComfyUI...", None
        yield chr(0x2705) + " done in 00:45", fake_url

    target_fn = _get_run_and_format_fn("sca12_replace", fake_run_video)
    yields = list(target_fn("ref.png", "drive.mp4", 81, 5, 0))

    last = yields[-1]
    status_text, media_html, err_upd, re_run_upd, open_dir_upd, btn_upd, status_bar_upd = last
    assert chr(0x7B49) not in media_html, (
        f"BUG: 视频闭包收尾 yield 把生成的视频覆盖成占位; got media_html={media_html!r}"
    )
    assert "<video" in media_html and fake_url in media_html, (
        f"BUG: 视频闭包收尾 yield 缺少 video 标签; got media_html={media_html!r}"
    )


def test_run_and_format_closure_no_media_yields_placeholder():
    """run_fn 全程没生成 media → 收尾 yield 仍走等待结果占位(行为不变)。"""
    def fake_run_fail(preset_name, *vals):
        yield "[READY] preparing...", None
        yield chr(0x274C) + " queue: not connected", None

    target_fn = _get_run_and_format_fn("zimage", fake_run_fail)
    yields = list(target_fn("a prompt", ["1024x1024"], 0))

    last = yields[-1]
    status_text, media_html, err_upd, re_run_upd, open_dir_upd, btn_upd, status_bar_upd = last
    assert chr(0x7B49) in media_html


# ---- _media_ext_from_url ----

def test_media_ext_comfyui_view_url_with_filename_query():
    """ComfyUI /view URL 的扩展名从 filename= query param 取, 不靠 URL endswith.

    bug 故事: 旧实现 _media_to_html 用 low_src.endswith(('.mp4', ...)) 判断视频,
    ComfyUI /view URL 结构是 /view?filename=...mp4&type=output&subfolder=...,
    URL 末尾是 &subfolder=... 而不是 .mp4 -> endswith 不命中 -> 误判成未知输出格式
    (banner 显示 \u201c\u672a\u77e5\u8f93\u51fa\u683c\u5f0f: <url>\u201d 而不是 <video> 标签).
    """
    # 真实生产 URL (用户截图)
    url = "http://127.0.0.1:8188/view?filename=scail-2_00094-audio.mp4&type=output&subfolder=SCAIL-2"
    assert scail2_app._media_ext_from_url(url) == ".mp4"
    # 出来的 HTML 应含 <video> 标签, 不是 \u672a\u77e5\u8f93\u51fa banner
    out = scail2_app._media_to_html(url, is_image=False)
    assert "<video" in out, f"\u672a\u77e5\u8f93\u51fa banner: {out!r}"
    assert "\u672a\u77e5\u8f93\u51fa" not in out


def test_media_ext_simple_url_still_works():
    """直接 URL (http://x/clip.mp4) 路径扩展名要正确识别 (回归保护)."""
    assert scail2_app._media_ext_from_url("http://x/clip.mp4") == ".mp4"
    assert scail2_app._media_ext_from_url("http://x/y.png") == ".png"
    assert scail2_app._media_ext_from_url("http://x/clip.MOV") == ".mov"


def test_media_ext_query_param_short_f():
    """测试用 URL (用 ?f= 而不是 ?filename=) 也要识别. 这是 tests/test_ui_helpers.py
    里的 fake URL 模式 -- 单元测试要兼容它."""
    assert scail2_app._media_ext_from_url("http://127.0.0.1:8188/view?f=clip_00001.mp4") == ".mp4"
    assert scail2_app._media_ext_from_url("http://127.0.0.1:8188/view?f=z_00001_.png") == ".png"


def test_media_ext_local_path():
    """本地路径用 Path.suffix."""
    assert scail2_app._media_ext_from_url(r"C:/foo/bar.mp4") == ".mp4"
    assert scail2_app._media_ext_from_url("/tmp/img.PNG") == ".png"


def test_media_ext_no_extension():
    """没扩展名 / 空串 / None 不崩."""
    assert scail2_app._media_ext_from_url("http://x/view") == ""
    assert scail2_app._media_ext_from_url("") == ""
    assert scail2_app._media_ext_from_url(None) == ""


def test_media_to_html_comfyui_view_url_renders_video_tag():
    """端到端: ComfyUI /view URL 在 _media_to_html 渲染成 <video> 而不是 \u672a\u77e5\u8f93\u51fa banner."""
    url = "http://127.0.0.1:8188/view?filename=scail-2_00094-audio.mp4&type=output&subfolder=SCAIL-2"
    out = scail2_app._media_to_html(url, is_image=False)
    assert "<video" in out
    assert "controls" in out
    assert url in out
    assert "\u672a\u77e5\u8f93\u51fa" not in out


def test_media_to_html_comfyui_view_url_with_f_param():
    """测试用 f= query param 的 ComfyUI /view URL 也要正确."""
    url = "http://127.0.0.1:8188/view?f=clip_00001.mp4"
    out = scail2_app._media_to_html(url, is_image=False)
    assert "<video" in out, f"got: {out!r}"
