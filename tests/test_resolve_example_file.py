"""_resolve_example_file 契约测试 (Flask 版, review 2026-07-28).

锁: 全部 example 资源统一从项目仓库 app/static/examples/ 读, 不再依赖 ComfyUI input 目录.
  - 返回值: "app/static/examples/<basename>" (项目相对路径, 让前端和 runner 都能识别)
  - 空 / 找不到: None
  - 绝对路径: 原样返回 (用户手填, 历史兼容)
"""
from pathlib import Path

from app.services import form_schema


def test_resolve_in_project_returns_project_path(tmp_path, monkeypatch):
    """example 资源在 app/static/examples/ -> 返回项目相对路径 "app/static/examples/<name>".

    review 2026-07-28: 不再读 COMFY_INPUT_DIR, example 一律走项目仓库.
    """
    examples = tmp_path / "app" / "static" / "examples"
    examples.mkdir(parents=True)
    (examples / "ref.png").write_bytes(b"x")
    monkeypatch.setattr(form_schema.config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(form_schema.config, "COMFY_INPUT_DIR", tmp_path / "input")

    result = form_schema._resolve_example_file("ref.png")
    assert result == "app/static/examples/ref.png", f"got {result!r}"


def test_resolve_relative_path_in_cwd_fallback(tmp_path, monkeypatch):
    """如果旧版本存的 example 路径是 CWD 下的文件 (不是项目 examples 也不是 COMFY_INPUT),
    仍按 CWD 兜底解析 (兼容历史 manifest 侧车)."""
    monkeypatch.setattr(form_schema.config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(form_schema.config, "COMFY_INPUT_DIR", tmp_path / "input")
    # 用 monkeypatch.chdir 在临时目录里建一个文件
    monkeypatch.chdir(tmp_path)
    staged = tmp_path / "staged.png"
    staged.write_bytes(b"x")
    result = form_schema._resolve_example_file("staged.png")
    # 相对 CWD 路径存在 -> 原样返回 (Path("staged.png") 走 str() 得 "staged.png")
    assert result == "staged.png", f"got {result!r}"


def test_resolve_empty_returns_none():
    """空文件名 -> None (让前端显示空缩略图)."""
    assert form_schema._resolve_example_file("") is None
    assert form_schema._resolve_example_file(None) is None


def test_resolve_missing_file_returns_none(tmp_path, monkeypatch):
    """文件不存在 -> None."""
    monkeypatch.setattr(form_schema.config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(form_schema.config, "COMFY_INPUT_DIR", tmp_path / "input")

    assert form_schema._resolve_example_file("ghost.png") is None


def test_resolve_absolute_path_returns_as_is(tmp_path, monkeypatch):
    """绝对路径 -> 原样返回 (用户手填绝对路径, 不强行归一化)."""
    examples = tmp_path / "app" / "static" / "examples"
    examples.mkdir(parents=True)
    f = examples / "abs.png"
    f.write_bytes(b"x")
    monkeypatch.setattr(form_schema.config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(form_schema.config, "COMFY_INPUT_DIR", tmp_path / "input")

    result = form_schema._resolve_example_file(str(f))
    assert result == str(f), f"got {result!r}"


def test_resolve_does_not_create_examples_cache(tmp_path, monkeypatch):
    """副作用: 不再创建 .examples_cache 目录 (Gradio 6 workaround 早已删除, 这里再锁一次)."""
    examples = tmp_path / "app" / "static" / "examples"
    examples.mkdir(parents=True)
    (examples / "ref.png").write_bytes(b"x")
    monkeypatch.setattr(form_schema.config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(form_schema.config, "COMFY_INPUT_DIR", tmp_path / "input")

    form_schema._resolve_example_file("ref.png")
    cache_dir = tmp_path / ".examples_cache"
    assert not cache_dir.exists(), ".examples_cache 不应该被创建"
