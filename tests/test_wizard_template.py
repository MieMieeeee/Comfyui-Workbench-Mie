"""工作流向导模板的关键视觉层级回归测试。"""
from pathlib import Path
import re


TEMPLATE = (
    Path(__file__).resolve().parent.parent / "app" / "templates" / "wizard.html"
).read_text(encoding="utf-8")


def _font_size(class_name: str) -> float:
    match = re.search(
        rf"\.{re.escape(class_name)}\s*\{{[^}}]*font-size:\s*([0-9.]+)em",
        TEMPLATE,
    )
    assert match, f"找不到 {class_name} 的 em 字号"
    return float(match.group(1))


def test_input_key_is_at_least_as_large_as_node_title():
    assert _font_size("wizard-pick-field-main") >= _font_size("wizard-pick-nodectx")


def test_input_key_is_rendered_before_node_context():
    key_markup = '<div class="wizard-pick-field-main" x-text="f.field"></div>'
    node_markup = '<div class="wizard-pick-nodectx" x-text="f.node_title || f.class_type || (\'Node \' + f.node_id)"></div>'
    assert TEMPLATE.index(key_markup) < TEMPLATE.index(node_markup)


def test_save_form_collects_description():
    assert 'x-model="saveDescription"' in TEMPLATE


def test_wizard_submits_selected_output_and_run_values():
    app_js = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "selected_output: sel" in app_js
    assert "values: this.runValues" in app_js
    assert "description: this.saveDescription.trim()" in app_js


def test_run_tab_uses_alpine3_panel_data_helper():
    app_js = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "function panelData(panel)" in app_js
    assert "const cfg = panel.__x.$data.presetCfg" not in app_js
    assert "const fv = panel.__x.$data.formValues" not in app_js
