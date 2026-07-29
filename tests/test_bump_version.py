"""scripts/bump_version.py 单元测试.

锁定契约:
- 无参数: 时间戳后缀更新到当前 UTC, semver 部分保留
- 传 1 个参数: 同时 bump semver
- WORKBENCH_VERSION 找不到/格式不对 -> exit 1
- 时间戳格式: YYYYMMDDHHMMSS (14 位数字)
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "bump_version.py"
PY = sys.executable


def _run_bump(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """跑一次 bump_version, 返回 (returncode, stdout, stderr)."""
    return subprocess.run(
        [PY, str(SCRIPT), *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """建一个最小 fake repo: scripts/ + app/config.py, 模拟 bump 运行环境."""
    scripts = tmp_path / "scripts"
    app = tmp_path / "app"
    scripts.mkdir(parents=True)
    app.mkdir(parents=True)
    (scripts / "bump_version.py").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (app / "config.py").write_text(
        'WORKBENCH_VERSION: str = "1.0.0+20260729141422"\n',
        encoding="utf-8",
    )
    return tmp_path


def test_bump_updates_only_timestamp(fake_repo: Path):
    """无参数: 时间戳变, semver 保持 1.0.0."""
    result = _run_bump(cwd=fake_repo)
    assert result.returncode == 0, result.stderr
    new = (fake_repo / "app" / "config.py").read_text(encoding="utf-8")
    m = re.search(r"WORKBENCH_VERSION:\s*str\s*=\s*\"([^\"]+)\"", new)
    assert m, "WORKBENCH_VERSION 找不到"
    value = m.group(1)
    assert re.fullmatch(r"1\.0\.0\+\d{14}", value), f"格式不对: {value}"


def test_bump_with_new_semver(fake_repo: Path):
    """传 2.1.0: semver 升, 时间戳也更新."""
    result = _run_bump("2.1.0", cwd=fake_repo)
    assert result.returncode == 0, result.stderr
    new = (fake_repo / "app" / "config.py").read_text(encoding="utf-8")
    m = re.search(r"WORKBENCH_VERSION:\s*str\s*=\s*\"([^\"]+)\"", new)
    value = m.group(1)
    assert re.fullmatch(r"2\.1\.0\+\d{14}", value), f"格式不对: {value}"


def test_bump_keeps_timestamp_format_14_digits(fake_repo: Path):
    """时间戳必须是 14 位数字 (YYYYMMDDHHMMSS), 跟 semver spec 一致."""
    _run_bump(cwd=fake_repo)
    new = (fake_repo / "app" / "config.py").read_text(encoding="utf-8")
    # 匹配 X.Y.Z+TIMESTAMP (timestamp 在引号前)
    m = re.search(r"\+(\d+)\"", new)
    assert m and len(m.group(1)) == 14, f"时间戳不是 14 位: {new[-80:]!r}"


def test_bump_real_config_works():
    """真项目的 app/config.py 也能正常 bump (端到端 sanity)."""
    import tempfile
    import shutil
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "scripts").mkdir()
        (td_path / "app").mkdir()
        shutil.copy(SCRIPT, td_path / "scripts" / "bump_version.py")
        shutil.copy(ROOT / "app" / "config.py", td_path / "app" / "config.py")
        result = _run_bump(cwd=td_path)
        assert result.returncode == 0, result.stderr
        new = (td_path / "app" / "config.py").read_text(encoding="utf-8")
        assert "WORKBENCH_VERSION" in new
        m = re.search(r"WORKBENCH_VERSION:\s*str\s*=\s*\"([^\"]+)\"", new)
        assert re.fullmatch(r"\d+\.\d+\.\d+\+\d{14}", m.group(1))


def test_bump_fails_when_pattern_missing(tmp_path: Path):
    """config.py 没有 WORKBENCH_VERSION 时, 脚本 exit 1."""
    scripts = tmp_path / "scripts"
    app = tmp_path / "app"
    scripts.mkdir(parents=True)
    app.mkdir(parents=True)
    (scripts / "bump_version.py").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (app / "config.py").write_text("# 空的\n", encoding="utf-8")
    result = _run_bump(cwd=tmp_path)
    assert result.returncode == 1
    assert "not found" in result.stderr
