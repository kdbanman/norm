# Concept & Requirement Details

This directory holds the **detailed layer** beneath
[`norm-concept.md`](../norm-concept.md) and
[`norm-requirements.json`](../norm-requirements.json): one file per question those two
documents leave open or under-specified.

Each file currently states an **open question** plus suspected answers/options, and ends with
a `## Resolution` heading marked `TODO`. As questions are decided, the answer goes under
`## Resolution` and the file becomes the durable record of *why* the behavior is what it is —
the document stays semantically correct after resolution (it's "the details," not "the
uncertainties").

Two kinds of file:

- **Spec clarification** — what the behavior *should be* (resolving these sharpens the
  requirements and unblocks concrete CLI assertions — session goal #1).
- **Verification approach** — how to prove a requirement that **can't** be a plain black-box
  CLI assertion (in-process inference, encryption at rest, negative security properties —
  session goal #2).

## Index

### Spec clarifications

| # | File | Question | Key reqs |
|---|---|---|---|
| 01 | [preprocess-window-coverage](01-preprocess-window-coverage.md) | What does "coverage" mean (idempotency + interval gating)? | PREPROCESS-003, INTERVAL-003/004 |
| 02 | [preprocess-row-invalidation](02-preprocess-row-invalidation.md) | What is a preprocess row's identity; what triggers recompute? | PREPROCESS-003, CONFIG-003/004 |
| 03 | [prompt-id-definition](03-prompt-id-definition.md) | What exactly is `prompt_id`? | data model §6, CONFIG-003 |
| 04 | [window-stride-edge-cases](04-window-stride-edge-cases.md) | N<K and trailing-remainder windows? | PREPROCESS-001/006 |
| 05 | [time-argument-semantics](05-time-argument-semantics.md) | `--from`/`--to`/`--last` interaction & defaults? | INTERVAL-001/002, PREPROCESS-004 |
| 06 | [capture-duration-rule](06-capture-duration-rule.md) | `duration_s` units & extension rule? | RECORD-001/003 |
| 07 | [idle-gap-accumulation](07-idle-gap-accumulation.md) | How does `idle_gap_s` accumulate across skips? | RECORD-002 |
| 08 | [dedupe-hash-inputs](08-dedupe-hash-inputs.md) | What feeds `phash`/`ax_hash`; AX normalization? | RECORD-003/004 |
| 09 | [uninitialized-store-behavior](09-uninitialized-store-behavior.md) | Behavior before `init` (absent ≠ locked)? | all data/report cmds |
| 10 | [prune-cascade-semantics](10-prune-cascade-semantics.md) | Does prune cascade to preprocess rows? | DATA-006 |
| 11 | [export-include-default](11-export-include-default.md) | `export --include` default & layout? | DATA-005 |
| 12 | [interval-report-storage](12-interval-report-storage.md) | Are interval reports ever stored? | INTERVAL-001/005 |
| 13 | [failure-exit-code-precedence](13-failure-exit-code-precedence.md) | Which exit code wins when several fail? | RECORD-007/008, SEC-004, PREPROCESS-005/006 |
| 14 | [cli-surface-and-flag-config-mapping](14-cli-surface-and-flag-config-mapping.md) | Complete flag list & flag↔config map? | GLOBAL-005, all |
| 15 | [output-string-contract](15-output-string-contract.md) | Are messages contractual; assertion strictness? | every text expectation |

### Verification approaches (goal #2)

| # | File | Property to verify | Key reqs |
|---|---|---|---|
| 16 | [inference-test-seam](16-inference-test-seam.md) | Observe the in-process `generate()` call | ARCH-001, PREPROCESS-002, INTERVAL-001, CONFIG-003/004 |
| 17 | [no-inference-server-verification](17-no-inference-server-verification.md) | No inference socket (vs. allowed weight download) | ARCH-001, PREPROCESS-002 |
| 18 | [encryption-at-rest-verification](18-encryption-at-rest-verification.md) | On-disk data is ciphertext | SEC-001, RECORD-001, PREPROCESS-001 |
| 19 | [keychain-key-and-acl-verification](19-keychain-key-and-acl-verification.md) | Keychain key exists & is scoped | INIT-001, SEC-002 |
| 20 | [negative-security-properties](20-negative-security-properties.md) | Login pw never read; transient decrypt; key zeroed | SEC-002/006, RECORD-006 |
| 21 | [no-elevated-privileges-verification](21-no-elevated-privileges-verification.md) | No sudo / no privileged helper | SEC-003, RECORD-009 |
| 22 | [capture-gating-test-harness](22-capture-gating-test-harness.md) | Deterministic idle + dedupe testing | RECORD-001/002/003/004 |
| 23 | [environment-failure-simulation](23-environment-failure-simulation.md) | Induce permission/dep/offline faults | RECORD-007, ENV-001, PREPROCESS-005 |
| 24 | [nondeterministic-report-assertions](24-nondeterministic-report-assertions.md) | What to assert despite LLM nondeterminism | PREPROCESS-001, INTERVAL-001 |
| 25 | [unattended-secret-input](25-unattended-secret-input.md) | Non-interactive passphrase (passwd, daemon) | INIT-003, SEC-005, RECORD-009 |

## Resolving

Fill the `## Resolution` section of a file with the decision (and a one-line rationale).
Several are linked: **01 → 02 → 03 → 04** form the preprocess/coverage cluster, and **16**
unblocks most of the goal-#2 verification items.
