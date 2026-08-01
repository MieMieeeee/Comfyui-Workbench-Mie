"""_resolve_example_file 解析行为契约锁.

背景: review 早期误判 '绝对路径找不到会落 CWD 同名文件', 复核发现第 305 行
`return ... if src.exists() else None` 已经正确 return None. 此测试把正确行为
钉死, 防未来回归.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import config
from app.services import form_schema


def test_empty_returns_none():
    assert form_schema._resolve_example_file("") is None
    assert form_schema._resolve_example_file(None) is None


def test_absolute_path_existing_returns_as_is(tmp_path):
    f = tmp_path / "ref.png"
    f.write_bytes(b"x")
    assert form_schema._resolve_example_file(str(f)) == str(f)


def test_absolute_path_missing_returns_none_not_cwd(tmp_path, monkeypatch):
    """绝对路径不存在 -> 直接 None, 即使 CWD 有同名文件也不命中."""
    # 在 CWD 放一个同名文件, 制造诱惑
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    bait = cwd_dir / "ghost.png"
    bait.write_bytes(b"x")
    monkeypatch.chdir(cwd_dir)
    missing_abs = tmp_path / "elsewhere" / "ghost.png"  # 不存在
    assert not missing_abs.exists()
    result = form_schema._resolve_example_file(str(missing_abs))
    assert result is None, f"绝对路径不存在应返 None, 实际 {result}"


def test_project_examples_hit(tmp_path):
    """项目 examples 里有同名文件 -> 返 'app/static/examples/<name>'."""
    # 用一个真实存在的 example 文件 (仓库自带) 验证
    real_example = config.REPO_ROOT / "app" / "static" / "examples" / "person.png"
    if not real_example.exists():
        pytest.skip("仓库无 app/static/examples/person.png")
    result = form_schema._resolve_example_file("person.png")
    assert result == "app/static/examples/person.png"
    # 传带前缀的形态也只看 basename
    result2 = form_schema._resolve_example_file("some/dir/person.png")
    assert result2 == "app/static/examples/person.png"


def test_relative_path_in_cwd_falls_back(tmp_path, monkeypatch):
    """相对路径 + CWD 命中 -> 返 CWD 绝对路径 (历史 staged 兼容路径)."""
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    f = cwd_dir / "staged.png"
    f.write_bytes(b"x")
    monkeypatch.chdir(cwd_dir)
    # 项目 examples 没这个名, 走第 3 分支 CWD
    assert (config.REPO_ROOT / "app" / "static" / "examples" / "staged.png").exists() is False
    result = form_schema._resolve_example_file("staged.png")
    assert result == str(f.resolve()) or result == "staged.png"


def test_unresolvable_returns_none():
    """既非绝对、项目 examples 没有、CWD 也没有 -> None."""
    result = form_schema._resolve_example_file("definitely_not_exist_xyz.png")
    assert result is None
