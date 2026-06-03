# 01 — What does "coverage" mean for preprocess/interval?

- **Type:** Spec clarification
- **Affects:** REQ-PREPROCESS-003 (idempotency), REQ-INTERVAL-003 (no coverage → exit 5), REQ-INTERVAL-004 (`--auto-preprocess`); concept §9, §10.9–10.12

## What's unclear

The whole preprocess → interval relationship hinges on the word **"covered,"** but it is
never defined. Two different notions are used interchangeably:

- **Idempotency** (10.9): a re-run should "detect covered windows; skip." Here "covered"
  is about *windows already summarized*.
- **Interval gating** (10.10–10.12): `report interval` errors unless preprocess output
  "covers the range." Here "covered" is about *a time range being summarized*.

We need one precise rule for each.

## Why it matters

Without it, three requirements are untestable: we can't say when a second `preprocess`
run should be a no-op, nor when `interval` should fail with exit 5 vs. succeed.

## Options / suspected answer

Define coverage at two levels:

1. **A window is "done"** iff a preprocess row already exists whose identity matches the
   window to be computed. (Window identity is the subject of [02] and [03].)
2. **An interval `[from, to]` is "covered"** iff one of:
   - **(a) Capture-set coverage** *(suspected best)* — every capture whose `ts ∈ [from,to]`
     is a member of at least one *done* window's `capture_ids`. Robust; directly drives
     `--auto-preprocess` (compute exactly the windows whose captures are uncovered).
   - **(b) Time-span coverage** — the union of done windows' `[window_start, window_end]`
     spans ⊇ `[from, to]`. Simpler, but mishandles gaps (idle periods) where there are no
     captures to summarize.
   - **(c) Overlap existence** — at least one done window overlaps the range. Weakest;
     likely too lenient (would let a 1-window summary "cover" a 24h interval).

Lean: **(a)**. It composes cleanly with the window edge-cases in [04] and the row-identity
rule in [02].

## Resolution

TODO
