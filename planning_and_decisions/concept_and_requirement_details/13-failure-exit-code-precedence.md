# 13 — Exit-code precedence when multiple preconditions fail

- **Type:** Spec clarification
- **Affects:** REQ-RECORD-007 (env, 6), REQ-RECORD-008 (auth, 3), REQ-SEC-004 (auth, 3), REQ-PREPROCESS-005 (model, 4), REQ-PREPROCESS-006 (not_found, 5); concept §11

## What's unclear

Several failure modes can be true **simultaneously**, but the order of checks — and thus
which exit code wins — is undefined. Example: `record --once` with **both** Screen Recording
permission missing (→ 6) **and** the store unlockable-failure (→ 3). REQ-RECORD-007 says 6,
REQ-SEC-004 says 3. Which runs first?

Similarly for `report preprocess` when the store is locked (3) **and** the model can't load
(4) **and** there are no captures (5).

## Why it matters

Tests isolate one failure at a time, but real invocations won't. A defined ordering makes the
exit codes deterministic and lets us write the negative tests without ambiguity.

## Options / suspected answer

Suspected check order (first failure wins):

1. **Usage / arg validation → 2** (before doing any work)
2. **Environment / permissions / missing native deps → 6**
3. **Auth / store unlock → 3**
4. **Model load → 4**
5. **Data presence (no captures / no coverage / unknown id) → 5**
6. Otherwise unexpected **runtime → 1**

Rationale: cheapest/most-fundamental preconditions first; you can't unlock a store you have
no permission to capture into, and you shouldn't load a model before you know the store
opens. Confirm this ordering and codify it.

## Resolution

TODO
