# -*- coding: utf-8 -*-
import re
from pathlib import Path

p = Path(r"F:\ComfyUIWebToRunWorkflow\app\scail2_app.py")
src = p.read_text(encoding="utf-8")

def _btn_block_for_label(label: str) -> str | None:
    """Find the gr.Button(...) block whose label (first string arg) contains `label`.
    Handles multi-line gr.Button(...) calls.
    """
    # Search for all gr.Button( occurrences and find the one whose first string arg matches
    for m in re.finditer(r"gr\.Button\(", src):
        start = m.start()
        # Find matching close paren
        depth = 0
        i = start
        while i < len(src):
            c = src[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        block = src[start : i + 1]
        # Extract first string arg
        first_str = re.search(r"[\"']([^\"']*)[\"']", block)
        if first_str and first_str.group(1) == label:
            return block
    return None

def _btn_size(label: str) -> str | None:
    block = _btn_block_for_label(label)
    if block is None:
        return None
    m = re.search(r"size\s*=\s*[\"']([^\"']+)[\"']", block)
    return m.group(1) if m else None

def test_run_btn_size_is_md_not_lg():
    label = chr(0x1F680) + chr(0x20) + chr(0x5f00) + chr(0x59cb) + chr(0x8fd0) + chr(0x884c)
    size = _btn_size(label)
    assert size == "md", (
        f"run_btn (\\u5f00\\u59cb\\u8fd0\\u884c) size={size!r}; expected 'md'. "
        f"User (2026-07-18) reported button too large at size=lg (85px vs 27.5px sm buttons). "
        f"size=md keeps it visually distinct without dwarfing the form."
    )

def test_re_run_btn_size_is_md_not_lg():
    label = chr(0x1F501) + chr(0x20) + chr(0x7528) + chr(0x76f8) + chr(0x540c) + chr(0x53c2) + chr(0x6570) + chr(0x518d) + chr(0x6765)
    size = _btn_size(label)
    assert size == "md", (
        f"re_run_btn (\\u7528\\u76f8\\u540c\\u53c2\\u6570\\u518d\\u6765) size={size!r}; expected 'md'."
    )

def test_run_btn_still_has_btn_run_primary_class():
    block = _btn_block_for_label(chr(0x1F680) + chr(0x20) + chr(0x5f00) + chr(0x59cb) + chr(0x8fd0) + chr(0x884c))
    assert block is not None, "run_btn not found"
    assert "btn-run-primary" in block, (
        f"run_btn must keep .btn-run-primary class for visual emphasis (theme gradient + glow). "
        f"Got block: {block[:300]}"
    )

def test_re_run_btn_still_has_btn_run_secondary_class():
    block = _btn_block_for_label(chr(0x1F501) + chr(0x20) + chr(0x7528) + chr(0x76f8) + chr(0x540c) + chr(0x53c2) + chr(0x6570) + chr(0x518d) + chr(0x6765))
    assert block is not None, "re_run_btn not found"
    assert "btn-run-secondary" in block, (
        f"re_run_btn must keep .btn-run-secondary class (UI_STYLE \\u00a72: deliberately low-saturation). "
        f"Got block: {block[:300]}"
    )
