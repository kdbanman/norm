# 22 — Making capture gating (idle + dedupe) deterministically testable

- **Type:** Verification approach
- **Affects:** REQ-RECORD-001, REQ-RECORD-002 (idle), REQ-RECORD-003/004 (dedupe); depends on [08]

## The gap

The idle gate reads real `HIDIdleTime`, and dedupe depends on real on-screen pixels + AX tree.
To assert "stored when present and changed," "skipped while idle," "deduped when unchanged,"
and "stored when only one of phash/AX changes," a test must **control** both the idle value
and the captured frame/AX content — neither of which is a CLI input today.

## Options

- **(a) Injection seam** *(suspected best)* — env/test hooks that feed a **scripted idle value**
  (e.g. `NORM_FAKE_IDLE=180`) and a **scripted frame + AX source** (`NORM_FAKE_CAPTURE=<dir>`
  of prepared image/AX pairs). Makes `record --once` fully deterministic and lets us construct
  the exact phash/AX combinations REQ-RECORD-003/004 require. Pairs with the hash-input
  definition in [08].
- **(b) Real-environment drive** — leave the machine idle for N seconds for the idle test;
  change/leave the screen for dedupe. Slow, flaky, hard in CI; useful as an occasional
  end-to-end smoke test only.
- **(c) Below-the-CLI unit tests** — test the gate/dedupe functions directly. Strong and fast,
  but not a black-box CLI assertion (acceptable under goal #2, complements (a)).

Recommendation: **(a)** for CLI-level acceptance + **(c)** for the hash/threshold math.

## Resolution

TODO
