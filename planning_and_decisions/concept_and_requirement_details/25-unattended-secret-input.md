# 25 — Non-interactive passphrase input (passwd, daemon)

- **Type:** Verification approach + spec clarification
- **Affects:** REQ-INIT-003, REQ-SEC-005 (`passwd`), REQ-RECORD-009 (daemon under a passphrase-wrapped store)

## The gap

`NORM_PASSPHRASE` covers non-interactive `init` (REQ-INIT-003), but two flows need more:

- **`passwd`** prompts for **old + new** (new twice). A single `NORM_PASSPHRASE` can't drive a
  two-secret rotation, so REQ-SEC-005 can't be tested non-interactively as specified.
- **Daemon (`record --install`) on a passphrase-wrapped store** has **no specified source** for
  the passphrase. A launchd agent runs unattended — where does the secret come from?

## Options

- **`passwd` test seam** *(suspected)* — define `NORM_OLD_PASSPHRASE` + `NORM_NEW_PASSPHRASE`
  (or accept old+new on stdin lines) so rotation is scriptable. Then REQ-SEC-005's
  "old fails (3) / new unlocks (0)" becomes a clean automated check.
- **Daemon + passphrase** — pick a policy:
  - **(a)** Disallow passphrase-wrapped stores under launchd (daemon requires the unwrapped
    Keychain-only key) — simplest and safest.
  - **(b)** Read `NORM_PASSPHRASE` from the agent's plist environment — **flag the risk**: the
    secret then sits in a plaintext plist, partially defeating the passphrase. If allowed,
    document the tradeoff.
  - **(c)** Use a Keychain-stored wrap the agent can unlock via its ACL, with no passphrase at
    runtime.

Decide the daemon policy (it's also a spec gap), then add the env seams for hermetic tests.

## Resolution

TODO
