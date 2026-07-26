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


def test_wizard_has_existing_workflow_editor_mode():
    assert "wizardMode === 'edit'" in TEMPLATE
    assert "编辑已有工作流" in TEMPLATE
    assert 'x-model="editPreset"' in TEMPLATE
    assert 'x-model="item.help"' in TEMPLATE
    assert '@dragstart="startEditDrag(idx)"' in TEMPLATE
    assert '@drop="dropEditItem(idx)"' in TEMPLATE
    assert "恢复内置默认" in TEMPLATE


def test_wizard_editor_calls_controlled_definition_apis():
    app_js = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "/api/wizard/editable-workflows" in app_js
    assert "/api/wizard/definition/${this.editPreset}" in app_js
    assert "method: 'PUT'" in app_js
    assert "method: 'DELETE'" in app_js
    assert "editDirty" in app_js
    assert "moveEditItem" in app_js


def test_wizard_editor_mobile_keeps_reorder_controls_visible():
    assert ".wizard-edit-list" in TEMPLATE
    assert "@media (max-width: 640px)" in TEMPLATE
    assert ".wizard-edit-move" in TEMPLATE


def test_run_clears_stale_example_while_new_result_is_generating():
    app_js = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "正在生成新结果" in app_js
    assert "this.resultHtml[presetName]" in app_js


def test_image_sizes_checkbox_uses_form_values_and_first_size_default():
    css = (Path(__file__).resolve().parent.parent / "app" / "static" / "app-flask.css").read_text(encoding="utf-8")
    assert ".size-option.selected" in css
    tmpl = (Path(__file__).resolve().parent.parent / "app" / "templates" / "run.html").read_text(encoding="utf-8")
    assert "(formValues[idx] || []).includes(sizeValue(opt))" in tmpl
    app_js = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "sizeChecked(opt, idx)" in app_js
    assert "formValues[idx]" in app_js
