#!/usr/bin/env python3
"""更新 app/config.py 里的 WORKBENCH_VERSION 时间戳后缀.

格式: MAJOR.MINOR.PATCH+YYYYMMDDHHMMSS (semver + UTC build metadata)

用法:
  python scripts/bump_version.py          # 仅更新时间戳, 保留 semver
  python scripts/bump_version.py 2.1.0  # 顺便升 semver (PATCH 数字)
"""
from __future__ import annotations
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 默认从 cwd 找 app/config.py (在 repo 根目录跑就行).
# __file__ 模式仅作 fallback (兼容 IDE 直接 Run 整个文件的情况).
import os as _os
_CONFIG_FROM_FILE = Path(__file__).resolve().parent.parent / "app" / "config.py"
_CONFIG_FROM_CWD = Path(_os.getcwd()) / "app" / "config.py"
CONFIG = _CONFIG_FROM_CWD if _CONFIG_FROM_CWD.exists() else _CONFIG_FROM_FILE

# 匹配 WORKBENCH_VERSION: str = "..."
# group 2 = semver 部分 (e.g. "1.0.0"), 不含 +timestamp
_PATTERN = re.compile(
    r'^(WORKBENCH_VERSION:\s*str\s*=\s*")([0-9]+\.[0-9]+\.[0-9]+)(?:\+[0-9A-Za-z-]+)?(")',
    re.MULTILINE,
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def main() -> int:
    new_semver = sys.argv[1] if len(sys.argv) > 1 else None
    timestamp = _now_utc()

    src = CONFIG.read_text(encoding="utf-8")
    m = _PATTERN.search(src)
    if not m:
        print(f"ERROR: WORKBENCH_VERSION pattern not found in {CONFIG}", file=sys.stderr)
        return 1

    if new_semver is None:
        new_semver = m.group(2)  # 保留原 semver

    new_value = f"{new_semver}+{timestamp}"
    new_src, count = _PATTERN.subn(rf"\g<1>{new_value}\g<3>", src)
    if count == 0:
        print(f"ERROR: pattern not replaced in {CONFIG}", file=sys.stderr)
        return 1

    CONFIG.write_text(new_src, encoding="utf-8")
    print(f"WORKBENCH_VERSION -> {new_value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
