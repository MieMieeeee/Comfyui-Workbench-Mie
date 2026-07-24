"""`_resolve_example_file` 契约测试 (Flask 版).

锁: 不再把文件复制到 .examples_cache/ (Gradio 6 安全 workaround 已废弃).
直接返回 ComfyUI input 目录下的纯文件名 (basename), 前端走 /comfy_input/<name>.
"""
from pathlib import Path

from app.services import form_schema


def test_resolve_returns_basename_not_cache_path(tmp_path, monkeypatch):
    """COMFY_INPUT_DIR 下的文件 -> 返回纯文件名, 不复制到 .examples_cache/."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "ref.png").write_bytes(b"x")
    monkeypatch.setattr(form_schema.config, "COMFY_INPUT_DIR", input_dir)
    monkeypatch.setattr(form_schema.config, "REPO_ROOT", tmp_path)

    result = form_schema._resolve_example_file("ref.png")
    assert result == "ref.png"
    # 关键: 不能是 .examples_cache 下的路径
    assert ".examples_cache" not in (result or "")


def test_resolve_does_not_create_examples_cache(tmp_path, monkeypatch):
    """副作用: 不再创建 .examples_cache 目录 (workaround 去掉了)."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "ref.png").write_bytes(b"x")
    monkeypatch.setattr(form_schema.config, "COMFY_INPUT_DIR", input_dir)
    monkeypatch.setattr(form_schema.config, "REPO_ROOT", tmp_path)

    form_schema._resolve_example_file("ref.png")
    cache_dir = tmp_path / ".examples_cache"
    assert not cache_dir.exists(), ".examples_cache 不应该被创建"


def test_resolve_empty_returns_none():
    """空文件名 -> None (让前端显示空缩略图)."""
    assert form_schema._resolve_example_file("") is None
    assert form_schema._resolve_example_file(None) is None


def test_resolve_missing_file_returns_none(tmp_path, monkeypatch):
    """文件不存在 -> None."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    monkeypatch.setattr(form_schema.config, "COMFY_INPUT_DIR", input_dir)
    monkeypatch.setattr(form_schema.config, "REPO_ROOT", tmp_path)

    assert form_schema._resolve_example_file("ghost.png") is None


def test_resolve_absolute_path_returns_basename(tmp_path, monkeypatch):
    """绝对路径也接受, 返回 basename."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    f = input_dir / "abs.png"
    f.write_bytes(b"x")
    monkeypatch.setattr(form_schema.config, "COMFY_INPUT_DIR", input_dir)
    monkeypatch.setattr(form_schema.config, "REPO_ROOT", tmp_path)

    result = form_schema._resolve_example_file(str(f))
    assert result == "abs.png"
