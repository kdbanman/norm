# 16 — A test seam for the in-process `generate()` call

- **Type:** Verification approach
- **Affects:** REQ-ARCH-001, REQ-PREPROCESS-002, REQ-INTERVAL-001, REQ-CONFIG-003, REQ-CONFIG-004

## The gap

Five requirements assert facts about the **in-process** inference call: that `generate()`
received **both** the window's image(s) **and** its AX text, that it used the **configured
prompt**, that it loaded the **configured `model_ref`**, and that it ran **in-process** (no
socket). Because inference is in-process, **none of this is observable over the network** —
the very property that makes "no server" true also makes the call invisible to black-box CLI
assertions. We need a deliberate observation seam. This is the single highest-leverage item
for goal #2.

## Options

- **(a) Injected fake model** *(suspected best)* — an env switch (e.g. `NORM_FAKE_MODEL=1`)
  makes `load()`/`generate()` resolve to a spy that (i) records each call's `model_ref`,
  prompt text, image count, and AX-text presence to a **trace file** the test reads, and
  (ii) returns canned markdown. Unblocks all five reqs, removes the multi-GB weight
  dependency, and makes report tests fast and deterministic (see [24]).
- **(b) `--trace` / `--dry-run` flag** — logs the would-be `generate()` arguments (and skips
  real generation). Good for CI; pairs well with (a).
- **(c) Structured `--verbose` log line** — REQ-PREPROCESS-002 already hints at this; lowest
  effort but couples tests to log formatting.

Recommendation: ship **(a) + (b)**. Define the trace schema (one JSON object per call) as part
of the spec so assertions are stable.

## Resolution

TODO
