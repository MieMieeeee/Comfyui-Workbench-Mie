"""5 个改动的回归锁:
   1. Klein Edit 的编辑提示词是 text 不是 prompt_pool
   2. run.html 不再包含 随机 3 条 按钮
   3. _open_output_dir 返回路径本体 (不再调本地 explorer)
   4. settingsTab.init 不重复拉 comfy_status (上面 appShell 拉过, 同一个路由会走 check_connection timeout)
   5. preview image 渲染的 HTML 没有多余的 ""” 造成图片不加载
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEF_KLEIN = (ROOT / "app" / "presets" / "definitions" / "klein_edit.json").read_text(encoding="utf-8")
RUN = (ROOT / "app" / "templates" / "run.html").read_text(encoding="utf-8")
FLASK = (ROOT / "app" / "flask_app.py").read_text(encoding="utf-8")
APP_JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")


def test_klein_edit_prompt_is_text_not_prompt_pool():
    """Klein Edit 的编辑提示词不应该是 prompt_pool (不要随机按钮)."""
    editor_idx = DEF_KLEIN.find("编辑提示词")
    assert editor_idx != -1, "definitions/klein_edit.json 找不到编辑提示词"
    after = DEF_KLEIN[editor_idx:editor_idx + 500]
    assert '"type": "prompt_pool"' not in after, "Klein Edit 编辑提示词仍是 prompt_pool"
    assert '"type": "text"' in after, "Klein Edit 编辑提示词不是 text"


def test_run_html_no_random_3_button():
    """run.html 里不应该出现随机 3 条按钮."""
    assert "随机 3 条" not in RUN, "run.html 仍有 随机 3 条 按钮"


def test_open_output_dir_fully_removed():
    """备忘: _open_output_dir 函数体和 /api/open_output_dir 路由都被删除.

    原本这个接口调本地 explorer/open, 中间试过 return path + 复制到剪贴板,
    都不适合远程访问 (用户看不到服务器本地路径, 也不走 ComfyUI /view).
    完全删除. 输出下游需要看产物时走 /comfy_output 代理.
    """
    assert "def _open_output_dir" not in FLASK, "_open_output_dir 函数体应该被删除"
    assert '/api/open_output_dir' not in FLASK, "/api/open_output_dir 路由应该被删除"




def test_settings_init_no_redundant_comfy_status():
    """settingsTab.init 不要再拉 /api/comfy_status, appShell 已拉过, 重拉会排队 check_connection(timeout)."""
    # 找到 settingsTab.init (settingsTab 里的初始化)
    import re
    settings_section = APP_JS.split("function settingsTab()", 1)[1]
    init_match = re.search(r"async init\(\) \{([^}]+)\}", settings_section, re.S)
    assert init_match, "找不到 settingsTab.init"
    init_body = init_match.group(1)
    # init 中不能出现 /api/comfy_status
    assert "/api/comfy_status" not in init_body, (
        "settingsTab.init 还在拉 /api/comfy_status, 会让设置页额外排队 check_connection(timeout)"
    )


def test_preview_image_html_no_broken_double_quote():
    """preview 图片的 inline style 不能出现 ""/>这种多余引号, 会让图片加载失败."""
    # 找出预览图片那段 JS, 检查是否有 "/>之前有多余的 ""
    assert 'margin:0 auto""/>' not in APP_JS, (
        "preview 图片 inline style 还有多余的 "" (margin:0 auto""/>), 会让图片加载失败"
    )