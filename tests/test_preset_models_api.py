"""GET /api/preset_models/<name> 路由契约测试."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import flask_app, config
from app.services import model_slots


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_preset_models_unknown_returns_404(client, monkeypatch):
    monkeypatch.setattr(config, "list_workflows", lambda: [])
    r = client.get("/api/preset_models/__nope__")
    assert r.status_code == 404


def test_preset_models_returns_slots(client, monkeypatch):
    monkeypatch.setattr(config, "list_workflows", lambda: [{"name": "zimage"}])

    slot = model_slots.SlotView(
        key="16::unet_name", node_id="16", class_type="UNETLoader",
        field="unet_name", required_filename="Z\\a.safetensors",
        available=["Z\\a.safetensors", "Z\\b.safetensors"], installed=True,
    )
    monkeypatch.setattr(model_slots, "slots_for_preset", lambda n: ([slot], True))

    r = client.get("/api/preset_models/zimage")
    assert r.status_code == 200
    data = r.get_json()
    assert data["fetched"] is True
    assert len(data["slots"]) == 1
    s = data["slots"][0]
    assert s["key"] == "16::unet_name"
    assert s["installed"] is True
    assert "Z\\b.safetensors" in s["available"]


def test_preset_models_degrades_on_exception(client, monkeypatch):
    """slots_for_preset 抛异常 → 降级空槽位, 不 500."""
    monkeypatch.setattr(config, "list_workflows", lambda: [{"name": "zimage"}])

    def boom(n):
        raise RuntimeError("comfy offline")

    monkeypatch.setattr(model_slots, "slots_for_preset", boom)
    r = client.get("/api/preset_models/zimage")
    assert r.status_code == 200
    data = r.get_json()
    assert data["slots"] == []
    assert data["fetched"] is False
