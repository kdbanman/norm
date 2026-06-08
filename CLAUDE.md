# norm

`norm` is a macOS (Apple Silicon) Python CLI that periodically captures a screenshot
plus the active screen's accessibility (AX) tree, stores both encrypted on disk, and
runs a local multimodal model (Gemma 4 via `mlx-vlm`, in-process) over the capture
history to emit markdown activity summaries.

The planning docs are the source of truth — read the relevant one before changing behavior:

- **Concept** — architecture, data model, security model, worked CLI examples:
  `planning_and_decisions/norm-concept.html`
- **Requirements** — pass/fail acceptance criteria, conventions, exit/error codes, test seams:
  `planning_and_decisions/norm-requirements.html`
- **Decision records** — `planning_and_decisions/` (see Documentation discipline below)

(These are large; open them when relevant rather than loading them every session, and
prefer the `normdev` readers — `req` for requirements, `dec` for decision records, plus the
concept worked examples cross-linked from `req show`. Do **not** hand-scrape the planning
HTML with ad-hoc shell/Python: it loses structure, leaves HTML entities raw, and silently
truncates the newest records.)

## Development workflow

Always work in this loop. Pick one or more outstanding requirements (as long as it's a cohesively scoped chunk) from the requirements doc, then:

1. **RED** — Write high-quality *executable* acceptance criteria covering the
   requirement(s) **before** implementing. Use whichever fits:
   - CLI scripts
   - Python unit + integration tests
   - Evals — markdown files with instructions to exercise the app and investigate the
     results, run by Claude subagents. Use these **only** where deterministic acceptance
     criteria can't work (e.g. judging nondeterministic report prose).

   The criteria must fail first — there is nothing implementing them yet.
2. **GREEN** — Implement until the criteria pass.
3. **REFACTOR** — Ruthlessly revisit the implementation: code quality, testability,
   maintainability, error-message quality, logging, module design, and the seams
   between modules.
4. **BONUS GREEN** — Write/refactor tests as the refactor requires.
5. **DOCUMENT** — Record non-obvious decisions (see below).
6. **COMMIT** — `git commit` with a high-quality message.

Prefer running the narrowest relevant tests during the loop, not the whole suite.

## Documentation discipline

Each place has a distinct job — **do not duplicate** across them. They may freely refer
to each other, but only via **durable** identifiers (requirement ids like `REQ-SEC-002`,
concept section ids, commit hashes) — **never line numbers**.

- **Concept doc** — what/why, architecture, data + security model.
- **Requirements doc** — pass/fail acceptance criteria and contracts.
- **Decision records** (`planning_and_decisions/`) — *extremely terse* records of
  non-obvious decisions that surfaced during implementation and that don't belong in the
  concept doc, the requirements doc, or a commit message. Refer out to requirement ids,
  concept sections, and commit hashes/messages as needed. Author by hand as HTML,
  consistent with the existing planning docs (`style.css`).
- **Commit messages** — what changed and why, for that change.
- **Code comments** — local, non-obvious "why" only.

## Non-obvious constraints

These are contracts the acceptance criteria assert on; ignoring them produces wrong code.
See the requirements doc for specifics.

- **Black-box tests.** Exit codes and the `--json` error envelope
  (`{"error":{"code","exit","message"}}`) are contractual and stable. **Never assert on
  report prose** — model output is nondeterministic; assert structure, side effects, and
  the inputs that reached `generate()`.
- **Test seams are not product features.** `NORM_FAKE_*` / `NORM_FORCE_*` env vars are
  hidden, test-only seams. The only user-facing env vars are `NORM_PASSPHRASE`,
  `NORM_OLD_PASSPHRASE`, `NORM_NEW_PASSPHRASE`.
- **Inference is in-process** via `mlx-vlm` — no server, socket, or daemon. Only
  `norm init` touches the network (to download weights); `record` and `report` must make
  **zero** network connections.
- **Encryption at rest is mandatory.** No plaintext capture / AX / index / report is ever
  written, except an explicit user-requested `--export` or `--output`.
- **macOS Apple Silicon only.** Runs non-sandboxed, never elevated (no sudo/setuid), and
  uses no macOS Keychain.

## Stack & tooling

Python CLI managed with [`uv`](https://docs.astral.sh/uv/). `src/` layout; package is
`norm` with console-script entry point `norm = norm.cli:main`. The version is the single
source of truth in `src/norm/__init__.py` (`__version__`), read dynamically by hatchling.

Key dependencies (added per iteration as needed): `macapptree` (screenshot + AX capture),
`mlx-vlm` (in-process inference), `imagehash` (dedupe), SQLCipher + AES-256-GCM + Argon2id
(encrypted store). The CLI skeleton itself has no runtime deps (stdlib `argparse`).

Canonical commands:

- `uv sync` — create/refresh the venv and install the project (editable) + dev deps.
- `uv run pytest` — run the test suite (narrow with `uv run pytest tests/test_x.py::name`).
- `uv run norm <args>` / `uv run python -m norm <args>` — run the CLI.

Acceptance tests are black-box: they invoke `python -m norm` as a subprocess and assert on
stdout/stderr/exit code (see `tests/test_global.py`).

### Developer tooling (`tools/normdev`)

The recurring TDD-loop chores live in a dev-only CLI (`tools/`, **not** shipped in the
wheel and **never** a `norm` subcommand — the product CLI surface is contractual,
REQ-GLOBAL-002). Its store driver also backs the pytest `store` fixture, so a manual
smoke run takes the exact same path as the acceptance tests. `make` wraps the common
cases; call the module directly for arg-taking forms:

- `make smoke` (`uv run python -m tools.normdev smoke [--keep]`) — stand up a throwaway
  encrypted store, drive `init`/`record`/`status`/`list` end-to-end through the capture
  seams, check the contract, and tear it down. Replaces ad-hoc `rm -rf /tmp/normsmoke; …`.
- `uv run python -m tools.normdev run [--base DIR] [--keep] [--capture] [--locked]
  [--no-init] [--env KEY=VAL ...] <norm args>` — run **one arbitrary** `norm` command
  against an ephemeral, auto-provisioned store (passphrase + fake-capture seams pre-wired);
  the norm command's stdout is forwarded verbatim so it stays pipeable. `--base DIR`
  reuses/persists a store across calls for a manual poke-session. `--env` (repeatable)
  layers extra seams onto the run — this is how you drive a command needing more than the
  unlock passphrase, e.g. `passwd`: the store is provisioned with the fixed harness
  passphrase (printed in the run banner), so pass that as `NORM_OLD_PASSPHRASE` —
  `normdev run --base DIR --env NORM_OLD_PASSPHRASE='correct horse battery staple'
  --env NORM_NEW_PASSPHRASE='new pw' passwd` (normdev flags must precede the norm command).
  The scriptable companion to `smoke` — use it instead of hand-rolling
  `mkdir /tmp/x; export NORM_PASSPHRASE; norm --config … init; …` to eyeball a new
  command's behaviour.
- `make req` / `make req-todo` (`uv run python -m tools.normdev req list [--outstanding]`)
  — list requirements (`✓` = referenced by a test) or just the ones no test covers yet.
- `uv run python -m tools.normdev req show REQ-XXX-NNN` — full pass/fail criteria for one
  requirement, where it's referenced, **and the matching concept §10.x worked example**.
  Use this to pick the next RED target without hand-slicing the planning HTML.
- `make dec` (`uv run python -m tools.normdev dec list`) / `uv run python -m tools.normdev
  dec show ADR-NNN` — list the decision records, or print one ADR in full (tags stripped,
  entities decoded, **untruncated**). Read these instead of scraping `norm-decisions.html`
  by hand; `dec show` accepts `ADR-006`, `adr-6`, or just `6`.
