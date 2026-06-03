# 23 — Simulating environment failures (permissions, missing deps, offline)

- **Type:** Verification approach
- **Affects:** REQ-RECORD-007 (no permission → 6), REQ-ENV-001 (macapptree missing → 6), REQ-PREPROCESS-005 (model unavailable offline → 4)

## The gap

Three exit codes depend on **environmental fault states** that are awkward to produce on a
healthy dev machine: revoked TCC permissions, an absent capture dependency, and
offline-with-uncached-weights. Without a way to induce them on demand, these codes can't be
tested reliably.

## Options

- **Permissions (→ 6):** `tccutil reset ScreenCapture` / `Accessibility` in a controlled
  environment, **or** *(suspected, more portable)* a fault-injection seam
  `NORM_FORCE_NO_PERMISSION=screen|ax` that forces the permission probe to report "denied," so
  the error path and message are tested without real TCC surgery.
- **Missing macapptree (→ 6):** force its import/native dependency to fail — e.g.
  `NORM_FORCE_NO_MACAPPTREE=1`, or run with a `PYTHONPATH` that shadows it with a module that
  raises `ImportError`. Assert exit 6 and that the message names the dependency.
- **Model unavailable offline (→ 4):** clear/redirect the HF cache (`HF_HOME` to an empty dir)
  **and** block network (or set HF offline mode); separately, pass an **invalid `model_ref`**
  for the "invalid model" variant. Assert exit 4 and that the message distinguishes the two
  causes where possible.

Recommendation: prefer **fault-injection env seams** over real OS-state mutation so the
negative tests are hermetic and CI-safe; keep one real-environment smoke test per code.

## Resolution

TODO
