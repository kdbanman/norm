# 12 — Are interval reports ever stored? ("not stored by default")

- **Type:** Spec clarification
- **Affects:** REQ-INTERVAL-001, REQ-INTERVAL-005 (`--output`); concept §6, §10.11

## What's unclear

The data model says interval reports are "written to file or stdout; **not stored by
default**." The phrase "by default" implies there is a way to store them — but **no flag or
command for that is specified anywhere.** REQ-INTERVAL-005 only covers `--output <file>`
(a plaintext file), which is not the same as storing an encrypted row in the index.

## Why it matters

Either there's an unspecified `--store`-style flag that needs requirements, or the "by
default" wording is misleading and should be removed. Tests shouldn't assume a storage path
that doesn't exist.

## Options / suspected answer

- **(a)** Add an explicit `--store`/`--save` flag that writes an **encrypted interval-report
  row** to the index (mirroring preprocess), distinct from `--output` (plaintext file).
  Would need its own requirement.
- **(b)** *(suspected simplest)* Interval reports are **never** persisted in the store; drop
  "by default" from the wording. Output goes to stdout or `--output <file>` only. Keeps the
  store model simpler; re-running interval is cheap if preprocess is cached.

## Resolution

TODO
