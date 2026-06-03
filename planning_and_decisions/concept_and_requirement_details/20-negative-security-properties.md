# 20 — Verifying "absence" security properties

- **Type:** Verification approach
- **Affects:** REQ-SEC-002 (login password never read), REQ-SEC-006 (transient in-memory decryption), REQ-RECORD-006 (key zeroed on exit)

## The gap

These are **negative guarantees** — "X never happens." You can't prove a universal negative
with a single CLI call; each needs its own technique, and some are only partially automatable.

## Per-property approach

- **Login password never read (SEC-002)** — there is no API to read the login password
  without an interactive auth prompt. Verify by: (i) asserting norm **never prompts** for it
  and runs non-interactively given only `NORM_PASSPHRASE`/Keychain; (ii) `dtrace`/`fs_usage`
  during a run shows no access to login-auth surfaces; (iii) **code review** that no
  PAM/`dscl`/login-keychain-password path is called. Largely audit + construction.

- **Transient, in-memory decryption (SEC-006)** *(most automatable)* — run
  `report preprocess/interval` while watching `data_dir`, `$TMPDIR`, and `/tmp` with FSEvents
  / `fs_usage`; assert **no new plaintext PNG/JSON file** appears during inference. The fake
  model [16] can hold the call open long enough to snapshot the filesystem mid-inference.

- **Key zeroed on exit (RECORD-006)** — near-untestable as black-box. Options: a **debug-build
  hook** that re-reads the buffer after zeroing and asserts it's clear; or accept as a
  **code-review-only** acceptance item. Decide which sub-properties are automated vs. manual.

## Recommendation

Split this requirement set explicitly into **automated** (transient-decryption FS watch) and
**manual/audit** (login-password path, key zeroing) acceptance items so the test plan is
honest about coverage.

## Resolution

TODO
