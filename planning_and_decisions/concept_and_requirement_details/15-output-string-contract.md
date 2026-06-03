# 15 — Are output strings contractual, and how strict are assertions?

- **Type:** Spec clarification (testing policy)
- **Affects:** essentially every requirement with a `stderr`/`stdout` text expectation

## What's unclear

Both docs quote specific human-readable messages — "idle 180s; skipped", "0 new windows",
"store already initialized; use --force", "duplicate; extended C(n)" — but never say whether
these are **contractual exact strings** or just **illustrative**. The requirements paraphrase
them loosely ("stderr explains…", "stderr names the missing permission").

## Why it matters

This decides how brittle the test suite is. Asserting exact prose means every wording tweak
breaks tests; asserting nothing about messages means we can't verify "names the missing
permission." We need a policy.

## Options / suspected answer

Suggested layered policy (lean):

1. **Exit codes are always contractual** — assert exactly.
2. **`--json` output (where supported) is contractual** — assert structure/keys/values.
3. **Human prose is NOT exact-matched.** Assert **stable substrings/keywords** that carry the
   requirement's intent (e.g., message contains `"force"` for init-clobber; names
   `"Screen Recording"` / `"Accessibility"` for permission errors).
4. Consider adding **stable message codes** or a **`--json` error envelope**
   (`{"code": "STORE_LOCKED", "exit": 3, ...}`) so negative tests can assert a code instead of
   prose. This is the most robust option and worth adding to the spec.

## Resolution

TODO
