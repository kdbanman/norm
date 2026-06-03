# 11 — `export --include` default and output layout

- **Type:** Spec clarification
- **Affects:** REQ-DATA-005; concept §10.15

## What's unclear

`export --from -1d --to now --out ./dump --include images,ax,reports` is always shown with an
explicit `--include`. Undefined:

- What is exported when `--include` is **omitted** — all artifact types, or is `--include`
  required?
- What does `reports` mean — preprocess markdown only, or interval reports too (interval
  reports aren't stored by default; see [12])?
- The on-disk layout (`./dump/{images,ax,reports}/...`) and filenames (cf. `show --export`
  writes `1042.png`, `1042.ax.json`).

## Why it matters

A test invoking `export` needs to know which files to expect on disk.

## Options / suspected answer

- **Suspected:** `--include` defaults to **all available types** (`images,ax,reports`).
- `reports` = stored **preprocess** markdown for the range (interval reports are produced
  on demand and not stored, so they're not exportable unless [12] adds storage).
- Layout: `./out/<type>/<capture_id or window_id>.<ext>`, plaintext (user-requested export),
  consistent with `show --export` naming.

## Resolution

TODO
