# CSS !important Audit (2026 July 17)

> Source: review [UI_REVIEW_2026-07-17.md](./UI_REVIEW_2026-07-17.md) P3-8.
> Status: documentation only. No code changes -- review notes "not now, but worth recording".

## Snapshot

```
Total !important in tokens.css:        451  (review measured 449; +-2 from line-counting diff)
Selectors that use !important:        113  (out of ~160 defined)
.gradio-container overrides:          41  (matched review)
```

## Top offenders (selectors with most !important)

| !important | selector | what it does |
| --- | --- | --- |
| 11 | `.btn-run-primary` | main CTA, override Gradio button defaults |
| 11 | `.btn-run-secondary` | secondary CTA, same purpose |
| 10 | `.history-filter-status label` | radio pills in history tab |
| 9  | `.sizes-cards` / `.sizes-cards label` | image size picker cards |
| 9  | `.run-status-bar` | status pill at top of run panel |
| 9  | `.custom-radio label` | nav Radio rows (post-P2-6) |
| 9  | `.btn-secondary-override` | secondary button reset |
| 8  | `.status-badge` / `.file-dropzone` / `.prose blockquote` / `.detail-prompt-body` / `.annotation-block` | various |

## Distribution

```
1 !important:  23 selectors   (one-off resets)
2 !important:  13 selectors
3 !important:  26 selectors
4-6 !important: 34 selectors
7-9 !important: 14 selectors
10+ !important: 3 selectors   (btn-run-primary / -secondary / history-filter-status)
```

## Why this is OK for now

`tokens.css` defines its own semantic class names (`.custom-radio`, `.btn-run-primary`,
`.file-dropzone`, `.section-header`) instead of styling Gradio's internal
`.svelte-xxxxx` hashes. The `!important` is only there to override Gradio defaults
on those semantic classes, not to fight Svelte-internal selectors. As long as our
class names don't change, Gradio 6 -> 7 upgrades should still let our overrides win.

## Risk vectors (long-term)

1. **Gradio 7 upgrade** -- if they change cascade priorities for their internal
   classes (`.block`, `.wrap`, `.label-wrap`), some of our `!important` may stop
   being necessary. Good opportunity to bulk-remove then.

2. **Inline `<style>` Gradio 6 emits** -- P3-7 had to add `body { background:
   var(--bg-app) !important; }` because of one such inline style. Each new
   Gradio version may emit new inline styles that we need to fight.

3. **Future contributors** -- 451 `!important` makes it hard to write a *local*
   override without joining the arms race. The `docs/UI_STYLE.md` principle
   ("custom-first, don't override Gradio natively if avoidable") is fine in
   intent but in practice we override a lot.

## What to do when we touch tokens.css again

- Don't add new `!important` without checking if there's a more specific selector.
- When bumping a class, prefer `--token` to encode the value (one place to change)
  rather than `!important` per-property.
- If you find yourself writing `!important` to fight another `!important`, that's
  a smell -- refactor selector specificity instead.

## Regenerating this audit

```bash
python -c "
import pathlib
src = pathlib.Path(r'F:\ComfyUIWebToRunWorkflow\app\static\tokens.css').read_text(encoding='utf-8')
print('!important:', src.count('!important'))
"
```
