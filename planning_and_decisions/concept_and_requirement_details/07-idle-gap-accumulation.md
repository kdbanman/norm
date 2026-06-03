# 07 — How is `idle_gap_s` accumulated across skipped ticks?

- **Type:** Spec clarification
- **Affects:** REQ-RECORD-002; concept §8, §10.4

## What's unclear

When the user is idle, the tick is skipped and the elapsed idle is "buffered" to stamp onto
**the next stored capture** as `idle_gap_s`. But if **several** idle ticks pass before the
next stored capture, it's undefined whether `idle_gap_s` is:

- the **last** observed `HIDIdleTime`,
- the **sum** of idle across the skipped ticks, or
- the **wall-clock gap** between the last stored capture and the next stored one.

## Why it matters

REQ-RECORD-002 only asserts `idle_gap_s >= observed idle`, which all three options satisfy
for a single tick — but the multi-tick loop behavior (REQ-RECORD-005) needs a defined rule,
and any exact assertion depends on it.

## Options / suspected answer

- **(a) Last observed idle** — simplest; loses information across multiple skips.
- **(b) Sum of skipped idle** — matches the "buffer idle gap" wording; can overcount if ticks
  overlap the same idle stretch.
- **(c) Wall-clock gap** *(suspected most meaningful)* — `idle_gap_s = ts(next stored) −
  ts(last stored) − accounted active time`. Directly answers "how long was nothing recorded,"
  which is the point of the field for time-accounting use cases.

Lean: **(c)**, falling back to **(a)** if we want to keep the loop stateless. Decide and make
the `>=` in REQ-RECORD-002 an exact relation if feasible.

## Resolution

TODO
