# 08 — What feeds `phash` / `ax_hash`, and is the AX tree normalized?

- **Type:** Spec clarification
- **Affects:** REQ-RECORD-003 (dedupe), REQ-RECORD-004 (store if only one changes); concept §8

## What's unclear

Dedupe stores nothing iff `phash` is within `phash_threshold` (Hamming) of the last frame
**AND** `ax_hash` is identical. Underspecified:

- **`phash`:** dHash via `imagehash`, presumably over the full screenshot. Confirm bit length
  and that `phash_threshold` (default 4) is Hamming distance on that hash.
- **`ax_hash`:** "AX-tree equality" via an exact hash of the AX JSON. **Is the JSON
  normalized first?** Real AX trees carry volatile attributes — focus ring, caret/selection,
  cursor position, scroll offset, timestamps, window IDs, live clocks. If any of these feed
  the hash, two visually identical frames will **never** match and dedupe will never fire.

## Why it matters

This is the difference between dedupe working at all and it being effectively dead. It also
makes REQ-RECORD-003/004 reproducible: to assert "dedupe fired" deterministically you must
know exactly which inputs are hashed (see also the capture harness in [22]).

## Options / suspected answer

- **`ax_hash`:** suspected — hash a **normalized** projection of the AX tree: keep stable
  structure/roles/labels/geometry buckets; **strip** volatile fields (focus, selection,
  caret, cursor, scroll position, timestamps, ephemeral ids). Document the exact strip list;
  it is part of the contract.
- **`phash`:** suspected — dHash of the rendered screenshot at a fixed downscale; threshold 4
  is Hamming distance. Confirm whether multi-monitor frames are hashed per-screen or combined
  (see [22]).

## Resolution

TODO
