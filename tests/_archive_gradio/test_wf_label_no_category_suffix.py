"""P0-2 regression lock: nav Radio label must not end with English category id.

review P0-2 says emoji already conveys category, so the `image` / `video` / `audio`
suffix is redundant + breaks language consistency + forces two-line rows.

Contract:
  - _wf_label(w) must not contain `image` / `video` / `audio` English suffix
  - must not end with bare category English word
  - emoji prefix must remain (review approves emoji as the category marker)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import scail2_app, config


def _all_workflows():
    out = []
    for w in config.list_workflows():
        label = scail2_app._wf_label(w)
        out.append((w["name"], w.get("category", "other"), label))
    return out


def test_wf_label_has_workflows():
    wf_list = _all_workflows()
    assert wf_list, "no workflows found, params.json lost preset"


def test_wf_label_no_english_category_suffix():
    wf_list = _all_workflows()
    for name, category, label in wf_list:
        for eng_cat in ("image", "video", "audio", "3d", "other"):
            assert f" · {eng_cat}" not in label, (
                f"preset {name!r} label has English suffix {eng_cat!r}: {label!r} -- "
                f"review P0-2: emoji already conveys category, text suffix is noise"
            )


def test_wf_label_no_bare_english_category_at_end():
    wf_list = _all_workflows()
    for name, category, label in wf_list:
        stripped = label.rstrip()
        if category and category != "other":
            assert not stripped.endswith(category), (
                f"preset {name!r} label ends with bare category={category!r}: {label!r}"
            )


def test_wf_label_keeps_emoji_prefix():
    for name, category, label in _all_workflows():
        icon = scail2_app._category_icon(category or "other")
        assert label.startswith(icon), (
            f"preset {name!r} label {label!r} missing emoji prefix {icon!r}"
        )
