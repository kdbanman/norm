# 06 — `duration_s` initial value and dedupe-extension rule (units)

- **Type:** Spec clarification
- **Affects:** REQ-RECORD-001, REQ-RECORD-003 ("duration_s extended"); concept §6, §10.3, §10.5

## What's unclear

`duration_s` is named in **seconds**, but the worked examples set/extend it using
**`interval`**, which is configured in **minutes** (`interval_minutes`, default 5):

- 10.3: new capture `duration_s = interval`
- 10.5: dedupe extends prior `duration_s = 300 + interval`

`300 + 5` (seconds + minutes) is inconsistent. Either `interval` here means
`interval_minutes × 60`, or the field/units are mismatched.

## Why it matters

REQ-RECORD-003 only requires `duration_s` to be **"extended"** (a monotonic increase), which
we *can* assert without the exact rule. But any exact-value assertion — and the meaning of
the stored number — needs the unit fixed.

## Options / suspected answer

- **Suspected:** `duration_s` is genuinely seconds. On store, `duration_s = interval_minutes
  × 60`. On dedupe, `prior.duration_s += interval_minutes × 60`. So 10.5's "300" is one
  default interval (5 min) already in seconds, and the extension adds another 300 → 600.
- The examples' use of `interval` is shorthand for "one interval's worth, in seconds."

Decision needed: confirm the unit, and confirm that with `--once --interval 1` (used by
REQ-GLOBAL-005) the stored `duration_s` is 60, not 1.

## Resolution

TODO
