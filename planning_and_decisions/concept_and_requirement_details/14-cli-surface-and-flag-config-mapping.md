# 14 — Complete CLI surface + flag ↔ config-key mapping

- **Type:** Spec clarification (table to complete)
- **Affects:** REQ-GLOBAL-005 (precedence), every command; conventions `config.keys`, `global_flags`

## What's unclear

The examples reference many flags, but there is **no complete per-command flag list**, and
the mapping between CLI flags and config keys is partial and **named differently**
(`--interval` ↔ `interval_minutes`, `--window` ↔ `window_k`, `--stride` ↔ `stride_j`,
`--idle-threshold` ↔ `idle_threshold_seconds`). Unknowns:

- Do `--model`, `--data-dir`, `--max-tokens`, `--phash-threshold` exist as flags?
- Several **config keys have no flag and no requirement:** `max_tokens`, `phash_threshold`,
  `data_dir`, `prompt_interval`. Are they CLI-overridable? Tested?

## Why it matters

Goal #1 (comprehensive CLI assertions) needs the full flag inventory and the precedence rule
(`CLI flag > ~/.norm > default`) testable for **every** overridable key, not just
`interval_minutes` (the only one in REQ-GLOBAL-005).

## Suspected mapping (to confirm/complete)

| Config key | CLI flag | Commands | Has requirement? |
|---|---|---|---|
| `interval_minutes` | `--interval` | record | REQ-GLOBAL-005, REQ-RECORD-005 |
| `idle_threshold_seconds` | `--idle-threshold` | record | REQ-RECORD-002 |
| `data_dir` | `--data-dir`? | all | none |
| `phash_threshold` | `--phash-threshold`? | record | implicit only |
| `model` | `--model`? | report | REQ-CONFIG-004 (via config) |
| `window_k` | `--window` | report preprocess | REQ-PREPROCESS-001 |
| `stride_j` | `--stride` | report preprocess | REQ-PREPROCESS-001 |
| `max_tokens` | `--max-tokens`? | report | none |
| `prompt_preprocess` | (config only?) | report preprocess | REQ-CONFIG-003 |
| `prompt_interval` | (config only?) | report interval | none (used in INTERVAL-001) |

Decision: confirm which keys are flag-overridable, name the flags, and add precedence
requirements (or explicitly mark "config-only").

## Resolution

TODO
