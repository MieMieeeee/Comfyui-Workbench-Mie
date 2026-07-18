"""E2E: filter to 0 results, then click a row -> no Invalid JSON error toast.

User 2026-07-18: clicking the history tab freezes the page; clicking an entry
pops up "Invalid JSON string: Input is a zero-length, empty document".

Root cause: _make_detail_from_run(None) and _on_history_row_select empty
placeholder tuples returned json_str=""; gr.JSON(value="") raised on the empty
string, producing the red toast + queue weirdness ("freeze").

Fix: json_str empty placeholder is now Python dict {} (gr.JSON.postprocess takes
the orjson.dumps branch instead of orjson.loads("")).

This test reproduces the user flow end-to-end and locks the regression:
  1. open the app
  2. click the history tab
  3. change preset filter to a value (likely 0-result combo)
  4. trigger df.select via row click OR via empty cache path
  5. expect NO error toast / NO Invalid JSON message / page remains responsive

Default off (requires --e2e): pytest --e2e tests/test_e2e_history_empty_json_no_error.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

pytestmark = pytest.mark.e2e


def _click_history_tab(pg):
    """Click the history tab button (button[role=tab])."""
    tab = pg.locator(chr(34) + "button[role=" + chr(34) + "tab]" + chr(34) + ":has-text(" + chr(34) + chr(0x5386) + chr(0x53f2) + chr(0x8bb0) + chr(0x5f55) + chr(34) + ")").first
    tab.wait_for(timeout=10000)
    tab.click()


# JS helpers. Defined as plain strings to avoid quote-nesting issues.
_HAS_INVALID_JSON_TOAST_JS = """
() => {
  const sels = [".toast-wrap", "[class*=toast]", "[class*=error]"];
  const re = /Invalid JSON|zero-length/i;
  for (const s of sels) {
    for (const el of document.querySelectorAll(s)) {
      const t = (el.textContent || "").trim();
      if (t && re.test(t)) return t.substring(0, 200);
    }
  }
  return null;
}"""


_DATAFRAME_MOUNTED_JS = """
() => {
  return !!document.querySelector(".custom-dataframe");
}"""


_PICK_LAST_PRESET_FILTER_JS = """
() => {
  const sel = [...document.querySelectorAll("select")].find(s => {
    const opts = [...s.options].map(o => o.text);
    return opts.some(o => /zimage|klein|sca12/.test(o));
  });
  if (!sel) return null;
  const last = sel.options[sel.options.length - 1];
  if (!last) return null;
  sel.value = last.value;
  sel.dispatchEvent(new Event("change", { bubbles: true }));
  return last.text;
}"""


_CLICK_FIRST_DATAFRAME_ROW_JS = """
() => {
  const row = document.querySelector(".custom-dataframe .virtual-row");
  if (!row) return false;
  row.click();
  return true;
}"""


def test_history_filter_zero_results_then_click_no_invalid_json(page):
    """Filter to a 0-result combo, click a row -> no "Invalid JSON" toast.

    Lock for the 2026-07-18 user bug. The fix is server-side (json_str "" -> {}),
    so this E2E exercises the empty placeholder path end-to-end."""
    pg, base_url = page
    pg_errors = []
    pg.on("pageerror", lambda err: pg_errors.append(str(err)))

    pg.goto(base_url, wait_until="networkidle", timeout=20000)
    time.sleep(2)

    _click_history_tab(pg)
    time.sleep(2)

    try:
        pg.wait_for_function(_DATAFRAME_MOUNTED_JS, timeout=10000, polling=200)
    except Exception:
        pytest.skip("history Dataframe did not mount within 10s -- env may lack data")

    # Change preset filter to a value likely to give 0 results.
    changed_to = pg.evaluate(_PICK_LAST_PRESET_FILTER_JS)
    time.sleep(2)

    # Click first row of (possibly empty) Dataframe.
    pg.evaluate(_CLICK_FIRST_DATAFRAME_ROW_JS)
    time.sleep(2)

    # CRITICAL: NO Invalid JSON error toast.
    toast = pg.evaluate(_HAS_INVALID_JSON_TOAST_JS)
    assert toast is None, f"Invalid JSON toast appeared after filter+click: {toast}"

    # Page still responsive (queue not deadlocked).
    try:
        pg.wait_for_function("() => 1 + 1", timeout=5000, polling=200)
    except Exception:
        pytest.fail("page JS unresponsive after filter+click -- Gradio queue deadlocked")

    relevant = [e for e in pg_errors if "Invalid JSON" in e or "zero-length" in e]
    assert not relevant, f"JS errors mentioning Invalid JSON: {relevant}"

    # Other tabs still work.
    RUN = chr(0x8fd0) + chr(0x884c)
    run_tab = pg.locator("button[role=" + chr(34) + "tab" + chr(34) + "]:has-text(" + chr(34) + RUN + chr(34) + ")").first
    run_tab.evaluate("el => el.click()")
    time.sleep(1)
    body = pg.evaluate("document.body.innerText")
    START_RUN = chr(0x5f00) + chr(0x59cb) + chr(0x8fd0) + chr(0x884c)
    assert START_RUN in body, f"returning to run tab failed -- page is frozen: {body[:200]}"


def test_history_tab_open_no_invalid_json_toast_on_startup(page):
    """Open history tab on a fresh page -> no "Invalid JSON" toast.

    Some users reported the error on initial tab open (cache miss before any
    row click). _refresh_history_details returns the empty placeholder on
    cache miss; if json_str were "" that path would raise too. Lock it."""
    pg, base_url = page
    pg_errors = []
    pg.on("pageerror", lambda err: pg_errors.append(str(err)))

    pg.goto(base_url, wait_until="networkidle", timeout=20000)
    time.sleep(2)

    _click_history_tab(pg)
    time.sleep(3)

    toast = pg.evaluate(_HAS_INVALID_JSON_TOAST_JS)
    assert toast is None, f"Invalid JSON toast on tab open: {toast}"

    relevant = [e for e in pg_errors if "Invalid JSON" in e or "zero-length" in e]
    assert not relevant, f"JS errors on tab open: {relevant}"

