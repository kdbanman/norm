# 19 — Verifying the Keychain data key and its ACL scoping

- **Type:** Verification approach
- **Affects:** REQ-INIT-001 (key exists), REQ-SEC-002 (distinct from login password), security model §7

## The gap

"A norm data key exists in the Keychain" with "ACL scoped to the norm binary" is checked via
the Keychain, not via norm's stdout. The **existence** of the item is easy to assert; the
**ACL scoping** is genuinely hard to verify from outside.

## Options

- **Existence** *(easy, executable)* — `security find-generic-password -s "norm:datakey"`
  returns success after `init` and absence before. Assert the item is present, is a
  generic-password item, and (via metadata) was created by norm.
- **Randomness / distinctness** — assert the key material is 256-bit and is **not** equal to
  or derived from the login password (supports REQ-SEC-002); this mostly has to be argued by
  construction + code review, since the raw bytes aren't meant to be extractable.
- **ACL scoping** *(hard)* — fully asserting "only the norm binary may read it" likely needs a
  Keychain-API harness or manual inspection. **Practical proxy:** delete/withhold the item and
  assert norm then reports the locked state (exit 3), closing the loop with REQ-SEC-004 — this
  proves the key is *the* gate even if it doesn't prove the ACL boundary.

Recommendation: automate existence + the locked-without-key proxy; flag ACL boundary as a
**manual/code-review** acceptance item (see [20]).

## Resolution

TODO
