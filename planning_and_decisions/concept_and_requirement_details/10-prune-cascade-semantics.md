# 10 — What does `prune` cascade to (preprocess rows, partial windows)?

- **Type:** Spec clarification
- **Affects:** REQ-DATA-006; concept §10.16; interacts with coverage [01]

## What's unclear

`prune --before -30d` "deletes matching index rows AND their blobs atomically (no orphans)."
But the data model has **captures** *and* **preprocess rows** (which reference
`capture_ids[]`). Undefined:

- Does pruning a capture also delete preprocess rows that **reference** it?
- What about a preprocess **window that straddles the cutoff** (some captures older than 30d,
  some newer)? Delete the row, keep it, or keep it but mark its captures gone?
- Does "matching" select rows by capture `ts`, by preprocess `window_end`, or both?

## Why it matters

If a preprocess row survives but its underlying captures are gone, `export`/`show`/re-`force`
can't reproduce it, and "coverage" [01] becomes inconsistent. Tests need to know exactly what
remains after a prune.

## Options / suspected answer

- **Suspected:** prune selects **captures** by `ts < cutoff`, deletes them and their blobs,
  **and** deletes any preprocess row referencing **at least one** pruned capture (a window is
  only meaningful if all its captures exist). All atomic, no orphan blobs.
- Alternative: prune preprocess rows only when **fully** older than the cutoff
  (`window_end < cutoff`), leaving straddling windows intact but with dangling
  `capture_ids` — rejected unless we explicitly allow dangling references.
- Confirm `--dry-run` reports both captures and cascaded preprocess rows in its count.

## Resolution

TODO
