"""
主题设置持久化契约 (config.THEME_SETTINGS_FILE 写入 + 读回)。

每次用户切主题 theme_radio.change 调用 _save_theme 落盘,
启动时 _load_saved_theme 读盘取上次值,如果失败回退到 _DEFAULT_THEME_ID。

覆盖契约:
  A. 文件不存在 → 默认
  B. 文件存在但损坏 / JSON 解析失败 → 默认 (不抛,UI 不崩)
  C. theme_id 在 themes.json 里找不到 → 默认 (避免脏数据污染启动)
  D. 写入 → 读回 一致 (roundtrip)
  E. IO 错误 (e.g. 父目录只读) 静默,UI 已经看到新主题,下次启动回到默认
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app, config


# ---------- A. 文件不存在 ----------

def test_load_saved_theme_returns_default_when_file_missing(tmp_path, monkeypatch):
    """启动时找不到 theme_settings.json → 回退 coral-orange,不崩。"""
    fake = tmp_path / "no-such-file.json"
    monkeypatch.setattr(config, "THEME_SETTINGS_FILE", fake)
    assert scail2_app._load_saved_theme() == "coral-orange"


# ---------- B. JSON 损坏 ----------

def test_load_saved_theme_returns_default_when_corrupted(tmp_path, monkeypatch):
    """文件存在但内容不是合法 JSON → 回退默认,不抛。"""
    fake = tmp_path / "broken.json"
    fake.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(config, "THEME_SETTINGS_FILE", fake)
    assert scail2_app._load_saved_theme() == "coral-orange"


def test_load_saved_theme_returns_default_when_empty_object(tmp_path, monkeypatch):
    """空对象 / 缺字段 → 默认。"""
    fake = tmp_path / "empty.json"
    fake.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(config, "THEME_SETTINGS_FILE", fake)
    assert scail2_app._load_saved_theme() == "coral-orange"


# ---------- C. theme_id 不在 themes.json 里 ----------

def test_load_saved_theme_returns_default_when_id_unknown(tmp_path, monkeypatch):
    """读到一个 themes.json 里不存在的 theme_id (e.g. 老主题被删) → 默认。"""
    fake = tmp_path / "stale.json"
    fake.write_text(json.dumps({"theme_id": "future-theme-not-yet"}), encoding="utf-8")
    monkeypatch.setattr(config, "THEME_SETTINGS_FILE", fake)
    assert scail2_app._load_saved_theme() == "coral-orange"


# ---------- D. roundtrip ----------

def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    """_save_theme('mint-tesla') 写入,_load_saved_theme() 读回同一字符串。"""
    fake = tmp_path / "rt.json"
    monkeypatch.setattr(config, "THEME_SETTINGS_FILE", fake)
    scail2_app._save_theme("mint-tesla")
    assert scail2_app._load_saved_theme() == "mint-tesla"


def test_save_writes_valid_json_with_expected_keys(tmp_path, monkeypatch):
    """写入的内容必须是合法 JSON,顶层含 theme_id 字段。"""
    fake = tmp_path / "schema.json"
    monkeypatch.setattr(config, "THEME_SETTINGS_FILE", fake)
    scail2_app._save_theme("cyber-blue")
    data = json.loads(fake.read_text(encoding="utf-8"))
    assert data.get("theme_id") == "cyber-blue"


# ---------- E. IO 错误静默 ----------

def test_save_silently_no_ops_on_io_error(tmp_path, monkeypatch):
    """父目录不可写 → _save_theme 不抛,UI 已经看到新主题不影响。"""
    fake = tmp_path / "readonly" / "x.json"
    monkeypatch.setattr(config, "THEME_SETTINGS_FILE", fake)
    scail2_app._save_theme("future-retro")
    assert not fake.exists()


# ---------- F. 不会误碰 themes.json ----------

def test_save_does_not_modify_themes_json(monkeypatch, tmp_path):
    """_save_theme 只写 THEME_SETTINGS_FILE,不能误碰 themes.json。"""
    fake = tmp_path / "x.json"
    monkeypatch.setattr(config, "THEME_SETTINGS_FILE", fake)
    themes_file = config.REPO_ROOT / "app" / "presets" / "themes.json"
    mtime_before = themes_file.stat().st_mtime
    scail2_app._save_theme("mint-tesla")
    mtime_after = themes_file.stat().st_mtime
    assert mtime_before == mtime_after
