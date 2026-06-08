"""Black-box acceptance tests for ``norm report`` (preprocess + dry-run).

Report content is nondeterministic, so these never assert on report prose. They
assert structure, side effects, and the inputs that reached ``generate()`` — the
latter via the hidden ``NORM_FAKE_MODEL`` seam, which swaps mlx-vlm load()/generate()
for a spy that returns canned markdown and appends one JSON record per call
({model_ref, prompt, prompt_id, n_images, has_ax_text}) to a trace file
(norm-requirements verification.report_assertions).

Covered:
* REQ-REPORT-001    — `report` with no subcommand prints usage and fails (exit 2).
* REQ-REPORT-002    — `--dry-run` previews planned work; loads no model, writes no rows.
* REQ-PREPROCESS-001 — windows == floor((N-K)/J)+1; rows store provenance.
* REQ-PREPROCESS-002 — both image(s) AND AX text AND the prompt reach generate().
* REQ-PREPROCESS-003 — idempotent on capture-set identity; --force overwrites.
* REQ-PREPROCESS-004 — honors --from/--to capture range.
* REQ-PREPROCESS-006 — errors NO_CAPTURES when there are no captures (exit 5).
* REQ-PREPROCESS-007 — errors NOT_ENOUGH_CAPTURES when N < window (exit 5).
* REQ-CONFIG-003   — the effective prompt reaches generate() and is flag-overridable.
* REQ-CONFIG-004   — the effective model_ref reaches generate() and is flag-overridable.
* REQ-INTERVAL-001 — aggregates preprocess markdown over the range; stores a row; re-run appends.
* REQ-INTERVAL-002 — a time range is required (exit 2).
* REQ-INTERVAL-003 — uncovered range: --strict errors (exit 5); non-interactive default summarizes.
* REQ-INTERVAL-004 — --auto-preprocess fills the gap without prompting.
* REQ-INTERVAL-005 — --output writes the markdown plaintext; the encrypted row is still stored.
* REQ-GLOBAL-010   — a non-interactive run takes the interactive default, never prompting.
"""

from __future__ import annotations

import json

from tools.normdev.harness import seed_captures

DEFAULT_MODEL = "mlx-community/gemma-4-e4b-it-4bit"
DEFAULT_PROMPT = "What was this user doing?"
INTERVAL_PROMPT = "What did the user do over the time interval?"


def _trace(path):
    """Parse the NORM_FAKE_MODEL JSONL trace into a list of generate() records."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _counts(store):
    return store.json_out(store.run("status", "--json"))


def _fake_model_env(trace_path):
    return {"NORM_FAKE_MODEL": str(trace_path)}


def _seeded(store, tmp_path, n):
    store.init()
    seed_captures(store, n, work_dir=tmp_path / "frames")


# ── REQ-REPORT-001: no subcommand → usage error ───────────────────────────────


def test_report_no_subcommand_is_usage_error(store):
    result = store.run("report")
    assert result.returncode == 2, result.stderr
    assert "preprocess" in result.stderr
    assert "interval" in result.stderr


def test_report_unknown_subcommand_is_usage_error(store):
    result = store.run("report", "frobnicate")
    assert result.returncode == 2, result.stderr


# ── REQ-PREPROCESS-006 / -007: no captures, too few ───────────────────────────


def test_preprocess_no_captures_errors(store):
    store.init()
    result = store.run("--json", "report", "preprocess")
    assert result.returncode == 5
    env = json.loads(result.stdout)["error"]
    assert env["code"] == "NO_CAPTURES"
    assert env["exit"] == 5


def test_preprocess_fewer_than_one_window_errors(store, tmp_path):
    _seeded(store, tmp_path, 2)
    result = store.run("--json", "report", "preprocess", "--window", "6", "--stride", "3")
    assert result.returncode == 5
    env = json.loads(result.stdout)["error"]
    assert env["code"] == "NOT_ENOUGH_CAPTURES"
    assert _counts(store)["preprocess"] == 0


# ── REQ-PREPROCESS-001 / -002: real run stores rows; both modalities reach generate ──


def test_preprocess_stores_expected_window_rows(store, tmp_path):
    _seeded(store, tmp_path, 4)
    trace = tmp_path / "trace.jsonl"
    result = store.run(
        "report", "preprocess", "--window", "2", "--stride", "2",
        extra_env=_fake_model_env(trace),
    )
    assert result.returncode == 0, result.stderr
    # floor((4-2)/2)+1 = 2 windows → 2 rows, 2 generate() calls.
    assert _counts(store)["preprocess"] == 2
    records = _trace(trace)
    assert len(records) == 2


def test_preprocess_passes_both_images_and_ax_and_prompt(store, tmp_path):
    _seeded(store, tmp_path, 4)
    trace = tmp_path / "trace.jsonl"
    store.run(
        "report", "preprocess", "--window", "2", "--stride", "2",
        extra_env=_fake_model_env(trace),
    )
    records = _trace(trace)
    assert records, "generate() was never called"
    for rec in records:
        assert rec["n_images"] == 2  # one image per capture in the window
        assert rec["has_ax_text"] is True
        assert rec["prompt"] == DEFAULT_PROMPT
        assert rec["prompt_id"]  # sha256 prefix persisted as provenance
        assert rec["model_ref"] == DEFAULT_MODEL


def test_preprocess_markdown_not_written_in_plaintext(store, tmp_path):
    _seeded(store, tmp_path, 4)
    trace = tmp_path / "trace.jsonl"
    store.run(
        "report", "preprocess", "--window", "2", "--stride", "2",
        extra_env=_fake_model_env(trace),
    )
    # No blob on disk may hold the canned markdown as plaintext (REQ-SEC-001).
    for blob in (store.data_dir / "blobs").glob("*.blob"):
        assert b"Activity summary" not in blob.read_bytes()


# ── REQ-PREPROCESS-003: idempotent; --force overwrites ────────────────────────


def test_preprocess_is_idempotent_without_force(store, tmp_path):
    _seeded(store, tmp_path, 4)
    trace = tmp_path / "trace.jsonl"
    env = _fake_model_env(trace)
    first = store.run("report", "preprocess", "--window", "2", "--stride", "2", extra_env=env)
    assert first.returncode == 0, first.stderr
    assert _counts(store)["preprocess"] == 2

    trace.unlink()  # isolate the second run's generate() calls
    second = store.run("report", "preprocess", "--window", "2", "--stride", "2", extra_env=env)
    assert second.returncode == 0, second.stderr
    assert "0 new windows" in second.stdout
    assert _counts(store)["preprocess"] == 2  # no duplicate rows
    assert _trace(trace) == []  # covered windows were not recomputed


def test_preprocess_force_overwrites_without_appending(store, tmp_path):
    _seeded(store, tmp_path, 4)
    trace = tmp_path / "trace.jsonl"
    env = _fake_model_env(trace)
    store.run("report", "preprocess", "--window", "2", "--stride", "2", extra_env=env)

    trace.unlink()
    forced = store.run("report", "preprocess", "--window", "2", "--stride", "2", "--force", extra_env=env)
    assert forced.returncode == 0, forced.stderr
    assert _counts(store)["preprocess"] == 2  # overwritten, not appended
    assert len(_trace(trace)) == 2  # both windows recomputed


# ── REQ-PREPROCESS-004: honors --from/--to ────────────────────────────────────


def test_preprocess_range_excludes_all_captures(store, tmp_path):
    _seeded(store, tmp_path, 4)
    # A --to in the distant past leaves zero captures in range → NO_CAPTURES.
    result = store.run("--json", "report", "preprocess", "--to", "2000-01-01T00:00:00")
    assert result.returncode == 5
    assert json.loads(result.stdout)["error"]["code"] == "NO_CAPTURES"


def test_preprocess_wide_range_includes_all_captures(store, tmp_path):
    _seeded(store, tmp_path, 4)
    trace = tmp_path / "trace.jsonl"
    result = store.run(
        "report", "preprocess", "--from", "2000-01-01T00:00:00", "--to", "2100-01-01T00:00:00",
        "--window", "2", "--stride", "2", extra_env=_fake_model_env(trace),
    )
    assert result.returncode == 0, result.stderr
    assert _counts(store)["preprocess"] == 2


# ── REQ-CONFIG-003 / -004: prompt + model overridable, reach generate() ───────


def test_model_flag_reaches_generate(store, tmp_path):
    # REQ-CONFIG-004: --model selects the model_ref that reaches generate().
    _seeded(store, tmp_path, 4)
    trace = tmp_path / "trace.jsonl"
    store.run(
        "report", "preprocess", "--window", "2", "--stride", "2", "--model", "my/custom-vlm",
        extra_env=_fake_model_env(trace),
    )
    assert all(rec["model_ref"] == "my/custom-vlm" for rec in _trace(trace))


def test_prompt_flag_reaches_generate(store, tmp_path):
    _seeded(store, tmp_path, 4)
    trace = tmp_path / "trace.jsonl"
    store.run(
        "report", "preprocess", "--window", "2", "--stride", "2", "--prompt", "CUSTOM PROMPT",
        extra_env=_fake_model_env(trace),
    )
    records = _trace(trace)
    assert records and all(rec["prompt"] == "CUSTOM PROMPT" for rec in records)


# ── REQ-REPORT-002: --dry-run previews; no model, no rows ──────────────────────


def test_preprocess_dry_run_previews_without_inference(store, tmp_path):
    _seeded(store, tmp_path, 4)
    trace = tmp_path / "trace.jsonl"
    result = store.run(
        "report", "preprocess", "--window", "2", "--stride", "2", "--dry-run",
        extra_env=_fake_model_env(trace),
    )
    assert result.returncode == 0, result.stderr
    assert "gemma" in result.stdout  # model_ref previewed
    assert DEFAULT_PROMPT in result.stdout  # effective prompt previewed
    assert "2" in result.stdout  # planned window count
    assert not trace.exists()  # generate() never called
    assert _counts(store)["preprocess"] == 0  # no rows written


def test_preprocess_dry_run_json_shape(store, tmp_path):
    _seeded(store, tmp_path, 4)
    result = store.run(
        "--json", "report", "preprocess", "--window", "2", "--stride", "2", "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["dry_run"] is True
    assert out["windows"] == 2
    assert out["model"] == DEFAULT_MODEL
    assert out["prompt"] == DEFAULT_PROMPT
    assert sorted(out["capture_ids"]) == [1, 2, 3, 4]


def test_interval_dry_run_previews_without_inference(store, tmp_path):
    _seeded(store, tmp_path, 6)  # >= default window_k so a window forms over the range
    trace = tmp_path / "trace.jsonl"
    result = store.run(
        "report", "interval", "--last", "24h", "--dry-run",
        extra_env=_fake_model_env(trace),
    )
    assert result.returncode == 0, result.stderr
    assert INTERVAL_PROMPT in result.stdout
    assert not trace.exists()
    counts = _counts(store)
    assert counts["interval_reports"] == 0
    assert counts["preprocess"] == 0


# ── REQ-INTERVAL-002: a time range is required ────────────────────────────────


def test_interval_requires_time_range(store, tmp_path):
    _seeded(store, tmp_path, 6)
    result = store.run("report", "interval")
    assert result.returncode == 2, result.stderr
    assert "--from" in result.stderr or "--last" in result.stderr


def test_interval_missing_range_is_usage_error_before_store_access(store):
    # A missing range is a usage error (exit 2) even before the store is opened,
    # so it outranks NOT_INITIALIZED (exit 5) in the precedence.
    result = store.run("report", "interval")
    assert result.returncode == 2, result.stderr


# ── REQ-INTERVAL-001: aggregate preprocess markdown over the range ─────────────


def _preprocess_all(store, tmp_path):
    """Preprocess the seeded captures so the interval range is fully covered."""
    result = store.run("report", "preprocess", extra_env=_fake_model_env(tmp_path / "pre.jsonl"))
    assert result.returncode == 0, result.stderr
    return result


def test_interval_aggregates_preprocess_and_stores_row(store, tmp_path):
    _seeded(store, tmp_path, 6)
    _preprocess_all(store, tmp_path)
    assert _counts(store)["preprocess"] == 1

    trace = tmp_path / "iv.jsonl"
    result = store.run("report", "interval", "--last", "24h", extra_env=_fake_model_env(trace))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()  # aggregated markdown emitted to stdout by default
    assert _counts(store)["interval_reports"] == 1  # one encrypted row persisted

    records = _trace(trace)
    assert len(records) == 1  # exactly one aggregation call
    rec = records[0]
    assert rec["n_summaries"] == 1  # the one preprocess summary reached generate()
    assert rec["n_images"] == 0  # aggregates summaries, NOT raw captures
    assert rec["prompt"] == INTERVAL_PROMPT  # prompt_interval, not prompt_preprocess
    assert rec["model_ref"] == DEFAULT_MODEL


def test_interval_rerun_appends_a_new_row(store, tmp_path):
    _seeded(store, tmp_path, 6)
    _preprocess_all(store, tmp_path)
    env = _fake_model_env(tmp_path / "iv.jsonl")
    store.run("report", "interval", "--last", "24h", extra_env=env)
    store.run("report", "interval", "--last", "24h", extra_env=env)
    assert _counts(store)["interval_reports"] == 2  # every run is stored


def test_interval_markdown_not_written_in_plaintext(store, tmp_path):
    _seeded(store, tmp_path, 6)
    _preprocess_all(store, tmp_path)
    store.run("report", "interval", "--last", "24h", extra_env=_fake_model_env(tmp_path / "iv.jsonl"))
    for blob in (store.data_dir / "blobs").glob("*.blob"):
        assert b"Interval report" not in blob.read_bytes()  # REQ-SEC-001


# ── REQ-INTERVAL-003: uncovered range — strict / non-interactive default ───────


def test_interval_strict_errors_when_uncovered(store, tmp_path):
    _seeded(store, tmp_path, 6)  # captures exist but were never preprocessed
    result = store.run("--json", "report", "interval", "--last", "24h", "--strict")
    assert result.returncode == 5, result.stderr
    env = json.loads(result.stdout)["error"]
    assert env["code"] == "COVERAGE_MISSING"
    assert env["exit"] == 5
    counts = _counts(store)
    assert counts["interval_reports"] == 0  # no row stored
    assert counts["preprocess"] == 0  # --strict did no work


def test_interval_noninteractive_default_summarizes_then_reports(store, tmp_path):
    _seeded(store, tmp_path, 6)  # not preprocessed
    trace = tmp_path / "iv.jsonl"
    # stdin is closed (DEVNULL) → non-interactive → default action: summarize, then report.
    result = store.run("report", "interval", "--last", "24h", extra_env=_fake_model_env(trace))
    assert result.returncode == 0, result.stderr
    counts = _counts(store)
    assert counts["preprocess"] == 1  # the missing window was summarized first
    assert counts["interval_reports"] == 1
    records = _trace(trace)
    assert any(r["n_images"] > 0 for r in records)  # window summarized from images
    assert any(r["n_summaries"] > 0 for r in records)  # then aggregated from summaries


def test_interval_noninteractive_shows_no_prompt(store, tmp_path):
    # REQ-GLOBAL-010: with no TTY (stdin closed), the interactive default is taken
    # automatically — no prompt is shown and the command does not block or error.
    _seeded(store, tmp_path, 6)  # uncovered range
    result = store.run("report", "interval", "--last", "24h", extra_env=_fake_model_env(tmp_path / "iv.jsonl"))
    assert result.returncode == 0, result.stderr
    assert "summarize now?" not in result.stderr.lower()
    assert "[y/n]" not in result.stderr.lower()
    assert _counts(store)["interval_reports"] == 1  # the default (summarize + report) ran


# ── REQ-INTERVAL-004: --auto-preprocess fills the gap without prompting ────────


def test_interval_auto_preprocess_fills_gap(store, tmp_path):
    _seeded(store, tmp_path, 6)
    result = store.run(
        "report", "interval", "--last", "24h", "--auto-preprocess",
        extra_env=_fake_model_env(tmp_path / "iv.jsonl"),
    )
    assert result.returncode == 0, result.stderr
    counts = _counts(store)
    assert counts["preprocess"] == 1
    assert counts["interval_reports"] == 1


# ── REQ-INTERVAL-005: --output writes plaintext; row still stored ─────────────


def test_interval_output_writes_file_and_stores_row(store, tmp_path):
    _seeded(store, tmp_path, 6)
    _preprocess_all(store, tmp_path)
    out = tmp_path / "week.md"
    result = store.run(
        "report", "interval", "--last", "7d", "--output", str(out),
        extra_env=_fake_model_env(tmp_path / "iv.jsonl"),
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    body = out.read_text()
    assert body.strip()  # aggregated markdown written to the file (plaintext)
    assert body not in result.stdout  # not also dumped to stdout
    assert _counts(store)["interval_reports"] == 1  # encrypted row still persisted


# ── store-access contract for report (REQ-GLOBAL-007) ─────────────────────────


def test_preprocess_uninitialized_exits_5(store):
    result = store.run("report", "preprocess")
    assert result.returncode == 5, result.stderr
    assert "init" in result.stderr.lower()


def test_preprocess_locked_exits_3(store, tmp_path):
    _seeded(store, tmp_path, 4)
    result = store.run("report", "preprocess", passphrase=None)
    assert result.returncode == 3, result.stderr


def test_interval_uninitialized_exits_5(store):
    result = store.run("report", "interval", "--last", "24h")
    assert result.returncode == 5, result.stderr
    assert "init" in result.stderr.lower()


def test_interval_locked_exits_3(store, tmp_path):
    _seeded(store, tmp_path, 6)
    _preprocess_all(store, tmp_path)
    result = store.run("report", "interval", "--last", "24h", passphrase=None)
    assert result.returncode == 3, result.stderr
