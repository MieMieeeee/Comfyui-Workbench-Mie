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
PARAMS = (ROOT / "app" / "presets" / "params.json").read_text(encoding="utf-8")
DEF_KLEIN = (ROOT / "app" / "presets" / "definitions" / "klein_edit.json").read_text(encoding="utf-8")
RUN = (ROOT / "app" / "templates" / "run.html").read_text(encoding="utf-8")
FLASK = (ROOT / "app" / "flask_app.py").read_text(encoding="utf-8")
APP_JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")


def test_klein_edit_prompt_is_text_not_prompt_pool():
    """Klein Edit 的编辑提示词不应该是 prompt_pool (不要随机按钮)."""
    # 两个 klein_edit 定义都要课: params.json 和 definitions/klein_edit.json
    for src_name, src in (("params.json", PARAMS), ("definitions/klein_edit.json", DEF_KLEIN)):
        # 找编辑提示词 出现位置
        editor_idx = src.find("编辑提示词")
        assert editor_idx != -1, f"{src_name} 找不到编辑提示词"
        assert editor_idx != -1, f"{src_name} 找不到编辑提示词"
        # 该区域里的 type 不能是 prompt_pool
        # 找 editor_idx 后面的 type
        after = src[editor_idx:editor_idx + 500]
        assert '"type": "prompt_pool"' not in after, f"{src_name} 编辑提示词仍是 prompt_pool"
        assert '"type": "text"' in after, f"{src_name} 编辑提示词不是 text"


def test_run_html_no_random_3_button():
    """run.html 里不应该出现随机 3 条按钮."""
    assert "随机 3 条" not in RUN, "run.html 仍有 随机 3 条 按钮"


def test_open_output_dir_returns_path_not_subprocess():
    """_open_output_dir 不再调本地文件管理器, 返回路径本体给前端复制."""
    block = FLASK.split("def _open_output_dir", 1)[1]
    # 跳过 docstring (三引号 docstring 可能包含描述中提到的关键词, 不能被当成代码检查)
    docstring_end = block.find('"""' + '\n', block.find('"""'))
    if docstring_end == -1:
        docstring_end = block.find('"""' + '\n', block.find('"""'))
    # 简单点: 查找 docstring 后面的下一个 docstring 闭合
    first_q = block.find('"""')
    body_start = block.find('"""', first_q + 3) + 3
    # 跳过 docstring 后面到函数末尾或下一个顶级语句
    end = block.find("\ndef ", body_start)
    body = block[body_start:end] if end != -1 else block[body_start:]
    # 判断函数体在 docstring 之后是否返回 path
    # 不能出现 explorer / xdg-open / Darwin open (只检查函数体, 不包括 docstring)
    for keyword in ("explorer", "xdg-open", "Darwin"):
        assert keyword not in body, f"_open_output_dir 函数体还在出现 {keyword}"
    # 应该返回路径 (path 字符串)
    assert "return path" in body, "_open_output_dir 应该返回 path"


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