# AGENTS.md -- ComfyUIWebToRunWorkflow

> Project-level context for Codex / AI agents working on this codebase.
> Main AGENTS.md (C:\Users\administered\.codex\AGENTS.md) covers tooling;
> this file covers project direction.

## Project identity

- The author is the maintainer of a **ComfyUI integration bundle + launcher**.
  This repo is the **companion multi-workflow WebUI** that ships with that launcher.
  It is not a standalone product.
- Built-in workflows (app/presets/*.json) are curated and validated by the author
  himself, with node-IO annotations. They are a **pre-vetted set**, not user-submitted
  third-party workflows.

## Trust model -- this section decides code direction

**Built-in workflows are known to run.**

- Do NOT assume workflows may hit plugin-compat / missing-node issues at runtime.
- app/workflow_validator.py stays as a **config-drift sanity check**
  (catches wrong node_id / field in params.json after a manual edit),
  NOT as a plugin-availability gate. It runs once after patch_workflow; fail = refuse to queue.
- app/health_check.py L2/L3 (models / custom nodes) stays -- but its audience is the
  **user's deployment environment** (which file the user's ComfyUI instance is missing),
  not the workflow's own trustworthiness. When it reports X missing, the message should
  say 'your ComfyUI instance is missing X', not 'workflow requires X, we did not install it'.
- Failure-investigation priority (shapes debug paths):
    1. User input (params, file size / format, prompt length)
    2. ComfyUI process / port status
    3. Resources (VRAM, disk, file-size limit)
    4. **Only last** should the workflow itself be suspected
- When writing new preflight / auto-recovery / fallback branches, do NOT stack defenses
  on the 'plugin might be missing' assumption.

## Workflow-addition path (data-driven, NO new code)

The author will keep providing new workflows. For each, he supplies a short note:
'these nodes are user input / output, here are their field names'.

Adding a workflow means touching ONLY data, in three possible files.
For the full recipe (field reference, validation flow, debug sequence), see
[`docs/ADDING_WORKFLOWS.md`](./docs/ADDING_WORKFLOWS.md).

| File | What to change |
| --- | --- |
| app/presets/{name}.json | the workflow template itself |
| app/presets/params.json | preset config: display_name / category / order / description / workflow_file / user_facing_inputs / example / fixed_patches / do_not_modify_warnings |
| app/presets/health_requirements.json | ONLY if the workflow adds new model / custom-node deps |

**If a new workflow does not fit existing schema, EXTEND the schema first
  (add a type to _build_input_component, add fields to params.json).
  Do NOT bypass schema with a one-off code path for one workflow.**

## Schema design direction -- minimize authoring pain

For each new workflow, the author writes a user_facing_inputs array in params.json.
Each entry needs at least (node_id, field, label, type, tier). This is the heaviest
authoring burden in the project. Convergence directions worth pursuing:

- 'type' is mostly inferrable from the workflow JSON (file:image / file:video / text /
  int / bool / image_sizes). Any direction that cuts required fields is good.
- When adding a new type, FIRST implement it in _build_input_component, only THEN
  let the author use it. Do NOT add a half-working type (current example: the
  'custom WxH comma-separated' branch of image_sizes is unreachable from the UI --
  it's half-working and should be reaped).
- do_not_modify_warnings is a memo for future maintainers, not user config --
  keep it lightweight.
- fixed_patches is a preset-level hardcoded patch (e.g. SCAIL2 two modes share one
  workflow JSON, differ only by patching node 353). This reuse mechanism is good;
  encourage it for new workflows.

## Local dev environment -- `.venv`

A project-local `.venv/` (Python 3.12.10) is the canonical dev environment. It
exists so the bundle launcher can later consume the same Python + deps by
copying the venv contents into its embedded Python distribution.

- `.venv/` is in `.gitignore`; everyone rebuilds from `requirements.txt`.
- Run tests through `.venv\Scripts\python.exe -m pytest tests -q`.
- Never install packages with system `pip` outside the venv -- the launcher
  copies `.venv/` wholesale, system-site-packages leakage will not survive the move.
- `requirements.txt` is the source of truth; if you add a dep, add it there
  AND verify `pip install -r requirements.txt` from a clean venv works.
- `start_webui.bat` is unchanged -- it auto-creates / reuses `.venv` and launches
  from it (the launcher side does not need to know).

## Relationship with the launcher

- port **8199** -- avoids Gradio default 7860 and ComfyUI's 8188.
- WebUI is decoupled from ComfyUI: WebUI failure does not affect ComfyUI; ComfyUI
  being down does NOT prevent opening WebUI (user configures URL in Settings tab).
- Health-check failure must give **actionable diagnosis** (port not listening ->
  'click Start in ComfyUI launcher'; model missing -> 'place X under
  ComfyUI/models/...'); never just 'cannot connect'.
- start_webui.bat pre-cleans PID holding 8199 and auto-pip-installs on first run.
  Do NOT change this behaviour -- the author designed it specifically so
  repeated debugging does not hit port conflicts.

## Defense layers -- do not lightly remove

| Module | What it guards |
| --- | --- |
| app/workflow_validator.py | config drift (params.json vs workflow JSON mismatch) |
| app/health_check.py | user-deploy-env diagnosis (L0 connect / L1 system / L2 model / L3 node) |
| app/history.py | per-run manifest sidecar (audit, replay, history tab data source) |
| app/scail2_app.py:_resolve_example_file | stages ComfyUI input-dir files to .examples_cache/ (Gradio 6 security requires files under CWD) |
| zimage schema wiring (nodes 6 / 13 / 3 / 9) | zimage goes through parse_sizes + extract_all_image_outputs; do not replace with free-text intake |
| app/scail2_app.py:_render_workflow_form / _media_to_html / _run_and_format | UI layer: preset panel rendering, output media -> HTML, status prefix dispatch. Style rules live in [`docs/UI_STYLE.md`](./docs/UI_STYLE.md) |

## UI conventions

The emoji palette (film-frame / framed-picture / rocket / scroll / check / cross / ...),
tab structure, last-run state persistence, and CSS class list are governed by
[`docs/UI_STYLE.md`](./docs/UI_STYLE.md). When adding new buttons, status prefixes, or
categories, register them there before shipping the change.

## Review / editing checklist

- Before suggesting 'add a defensive check', ask: does this assumption hold under the
  trust model above? If not, skip it.
- Before suggesting 'rewrite this helper', read docs/DECISIONS.md first -- every
  decision there has a rationale.
- Before suggesting 'split this module', check whether the data-driven principle
  forbids it -- new functionality should be data-only, not new modules.
- When writing new copy / help text, use **user perspective** (users do not know
  what node ID 367 means). Never leak node numbers into UI copy.
