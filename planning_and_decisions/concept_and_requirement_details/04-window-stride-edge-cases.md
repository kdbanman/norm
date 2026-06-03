# 04 — Window/stride edge cases (too few captures, trailing remainder)

- **Type:** Spec clarification
- **Affects:** REQ-PREPROCESS-001, REQ-PREPROCESS-006; concept §9, §10.8

## What's unclear

The window count formula `floor((N − K) / J) + 1` is consistent across both docs
(N=12, K=6, J=3 → 3 windows), but two boundary cases are undefined:

1. **Fewer captures than the window (N < K).** The formula goes to 0 or negative.
   E.g. N=4, K=6, J=3 → `floor(-2/3)+1 = 0`. Is this exit 0 with "0 windows," or exit 5
   ("not enough captures")? Only **N = 0** is specified today (REQ-PREPROCESS-006 → exit 5).

2. **Trailing remainder.** When `(N − K)` isn't a multiple of `J`, the last captures fall
   into no window. E.g. N=13, K=6, J=3 → 3 windows covering indices 0–11; **capture 12 is
   never summarized.** Is the tail dropped, or do we emit a final short/shifted window?

## Why it matters

These cases decide the exact pass count for REQ-PREPROCESS-001 and interact directly with
"coverage" [01] and `--auto-preprocess` (an uncovered tail capture could force an extra
window every run).

## Options / suspected answer

- **N < K:** suspected — succeed with **0 windows, exit 0** (it's not an error to lack a full
  window yet); reserve exit 5 strictly for **0 captures**. Alternative: treat `0 < N < K` as
  exit 5 too. Pick one and make it explicit.
- **Trailing remainder:** suspected — **drop the tail** (matches the bare `floor` formula);
  the next captures will be picked up once enough accumulate to start a new window. Document
  this explicitly so "coverage" [01] doesn't treat the dropped tail as perpetually
  "uncovered." Alternative: emit a final partial window of size `< K` (changes the count
  formula and the REQ-PREPROCESS-001 assertion).

## Resolution

TODO
