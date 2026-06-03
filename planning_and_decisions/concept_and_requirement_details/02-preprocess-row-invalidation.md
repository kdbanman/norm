# 02 — What is a preprocess row's identity, and what invalidates it?

- **Type:** Spec clarification
- **Affects:** REQ-PREPROCESS-003 (idempotent unless `--force`), REQ-CONFIG-003 (prompt change), REQ-CONFIG-004 (model change); concept §6, §10.9

## What's unclear

A preprocess row stores `window_start, window_end, capture_ids[], model, prompt_id,
markdown_ref`. Idempotency "skips covered windows," but it is not stated **which fields
form the row's identity** — i.e., what makes a window count as "already done."

The tension: if identity is *just* the captures/window, then changing the prompt
(REQ-CONFIG-003) or model (REQ-CONFIG-004) would NOT trigger a recompute on the next run,
silently contradicting those requirements. If identity *includes* model + prompt, then a
prompt/model change naturally produces "new" (uncovered) windows.

## Why it matters

Determines the pass condition for REQ-PREPROCESS-003 and whether CONFIG-003/004 can be
verified by a plain re-run rather than only via `--force`.

## Options / suspected answer

- **Suspected:** identity = `(capture_ids, model, prompt_id)`. A window is "done" only if a
  row exists matching all three. Changing model or prompt makes prior rows non-matching, so
  the next run recomputes those windows without `--force`. `--force` recomputes even on an
  exact identity match.
- Alternative: identity = `(window_start, window_end)` only, and rely on `--force` for
  prompt/model changes. Rejected — makes CONFIG-003/004 awkward and surprising.

Open sub-question: on recompute, do we **overwrite** the existing row (10.9 says `--force`
"overwrites the 3 rows") or **append** a new row and keep history? Suspected: overwrite for
`--force`; for a model/prompt change, also overwrite (one summary per window per current
config), unless we deliberately want a version history.

See [01] (coverage) and [03] (`prompt_id`).

## Resolution

TODO
