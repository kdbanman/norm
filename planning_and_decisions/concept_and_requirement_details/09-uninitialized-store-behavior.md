# 09 — How do commands behave before `init` (no store at all)?

- **Type:** Spec clarification
- **Affects:** all data/report/status commands; concept §10 (only `init` states are enumerated)

## What's unclear

The worked examples cover `init` and `init` over an existing store, plus "store **locked**"
(10.20 → exit 3). But the **"never initialized"** state — no `~/.norm`, no `data_dir`, no
index, no Keychain key — is not enumerated for `status`, `list`, `show`, `export`, `prune`,
`record`, `report`, or `config get/set`.

"Locked" (key absent but store exists) and "absent" (store was never created) are different
situations and may warrant different exit codes/messages.

## Why it matters

Every command needs a defined behavior from a clean machine. Tests will run against a
freshly-created home with nothing initialized.

## Options / suspected answer

- **Suspected:** commands that require the store fail fast with a clear **"not initialized;
  run `norm init`"** message. Exit code candidates:
  - **5 (not_found)** — the store/index doesn't exist *(suspected best: it's a missing
    resource, distinct from a present-but-locked store at exit 3).*
  - **3 (auth)** — treat "no key/no store" uniformly as not-unlockable. Simpler, but conflates
    "absent" with "locked."
  - **2 (usage)** — least appropriate; this isn't an argument error.
- `config set` may be a special case: does it create `~/.norm` on demand, or also require
  `init` first? Suspected — `config` operates on `~/.norm` only and works without a store,
  but errors if `~/.norm` is absent until `init` writes it.

## Resolution

TODO
