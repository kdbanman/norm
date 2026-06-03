# 05 — `--from` / `--to` / `--last` semantics and interaction

- **Type:** Spec clarification
- **Affects:** REQ-INTERVAL-001/002, REQ-PREPROCESS-004, REQ-DATA-002/005, REQ-DATA-006 (`--before`); conventions `time_args`

## What's unclear

The three time flags are used interchangeably in the examples, but their relationships
aren't defined:

- **Combination:** what happens if `--last 24h` is given *together with* `--from`/`--to`?
  Error, or does one win?
- **Defaults:** if only `--from` is given, is `--to` implicitly `now`? If neither is given to
  `report preprocess` / `list`, is the range "all captures"? (`report interval` requires a
  range per REQ-INTERVAL-002 — confirm.)
- **Asymmetry:** conventions say `--from` accepts relative (`-24h`, `yesterday`) but `--to`
  accepts only ISO-8601 or `now`. Is `--to -1h` really invalid while `--from -1h` is valid?
- **Calendar words:** `yesterday` — which timezone and day boundaries (local? DST edges?).

## Why it matters

Range parsing underlies nearly every data/report command. Tests need exact rules for
defaults, precedence, and which forms are accepted on which flag.

## Options / suspected answer

- **`--last D`** = sugar for `--from = now − D`, `--to = now`. Make it **mutually exclusive**
  with `--from`/`--to` (combining → usage error, exit 2).
- **Defaults:** `--to` defaults to `now` when only `--from` is given. For `preprocess`/`list`,
  omitting all range flags = **all captures**. `report interval` with no range = exit 2
  (already required).
- **Symmetry:** allow relative offsets on **both** `--from` and `--to` (revise the doc's
  asymmetry), so `--to -1h` is valid. Resolve all relative/`now` values against a single
  command-start timestamp.
- **Calendar words:** resolve in the **local timezone**; `yesterday` = `[00:00, 24:00)` of
  the prior local day.

## Resolution

TODO
