"""Black-box acceptance tests for ``norm prune`` (REQ-DATA-006).

``prune --before <cutoff>`` deletes captures older than the cutoff and their
image/AX blobs atomically (no orphans), but RETAINS preprocess summaries and
interval reports unless ``--include reports`` is given. ``--dry-run`` reports the
counts that would be removed and deletes nothing.

Seeded captures all carry ~now timestamps, so the cutoff is exercised in both
directions with absolute bounds: a far-future cutoff matches everything, an ancient
cutoff matches nothing. Counts come from ``status --json`` and on-disk blob files —
never from internal state.
"""

from __future__ import annotations

import json

from tools.normdev.harness import seed_captures


def _fake_model_env(trace_path):
    return {"NORM_FAKE_MODEL": str(trace_path)}


def _counts(store):
    return store.json_out(store.run("status", "--json"))


def _blobs(store):
    return list((store.data_dir / "blobs").glob("*.blob"))


def _seed_full(store, tmp_path, n=6):
    """Seed ``n`` captures + one preprocess summary + one interval report."""
    store.init()
    seed_captures(store, n, work_dir=tmp_path / "frames")
    pre = store.run("report", "preprocess", extra_env=_fake_model_env(tmp_path / "pre.jsonl"))
    assert pre.returncode == 0, pre.stderr
    iv = store.run("report", "interval", "--last", "24h", extra_env=_fake_model_env(tmp_path / "iv.jsonl"))
    assert iv.returncode == 0, iv.stderr


_FUTURE = "2100-01-01T00:00:00"
_ANCIENT = "2000-01-01T00:00:00"


# ── --dry-run reports counts and deletes nothing ──────────────────────────────


def test_prune_dry_run_reports_counts_and_deletes_nothing(store, tmp_path):
    # REQ-DATA-006: --dry-run reports would-remove counts; deletes nothing.
    _seed_full(store, tmp_path)
    before = _counts(store)
    blobs_before = len(_blobs(store))

    result = store.run("--json", "prune", "--before", _FUTURE, "--dry-run")
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["captures"] == 6  # all six are older than the cutoff
    assert out["preprocess"] == 0  # not targeted without --include reports
    assert out["interval_reports"] == 0

    assert _counts(store) == before  # nothing removed
    assert len(_blobs(store)) == blobs_before


def test_prune_dry_run_include_reports_counts_summaries(store, tmp_path):
    _seed_full(store, tmp_path)
    result = store.run("--json", "prune", "--before", _FUTURE, "--dry-run", "--include", "reports")
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["captures"] == 6
    assert out["preprocess"] == 1
    assert out["interval_reports"] == 1
    assert _counts(store)["captures"] == 6  # still deletes nothing


# ── default: captures removed, summaries/reports retained, no orphans ─────────


def test_prune_default_removes_captures_retains_reports(store, tmp_path):
    # REQ-DATA-006: captures with ts<cutoff removed; preprocess/interval RETAINED.
    _seed_full(store, tmp_path)
    result = store.run("prune", "--before", _FUTURE)
    assert result.returncode == 0, result.stderr
    counts = _counts(store)
    assert counts["captures"] == 0
    assert counts["preprocess"] == 1  # retained even though its captures are gone
    assert counts["interval_reports"] == 1


def test_prune_removes_capture_blobs_without_orphans(store, tmp_path):
    # REQ-DATA-006: image/AX blobs removed atomically — no blob orphaned on disk.
    _seed_full(store, tmp_path)
    result = store.run("prune", "--before", _FUTURE)
    assert result.returncode == 0, result.stderr
    # The only surviving blobs are the two retained report markdowns (1 preprocess
    # + 1 interval); every capture image/AX blob is gone, none left orphaned.
    assert len(_blobs(store)) == 2


# ── --include reports also removes summaries and reports ──────────────────────


def test_prune_include_reports_removes_everything(store, tmp_path):
    # REQ-DATA-006: --include reports also removes preprocess + interval rows + blobs.
    _seed_full(store, tmp_path)
    result = store.run("prune", "--before", _FUTURE, "--include", "reports")
    assert result.returncode == 0, result.stderr
    counts = _counts(store)
    assert counts["captures"] == 0
    assert counts["preprocess"] == 0
    assert counts["interval_reports"] == 0
    assert _blobs(store) == []  # every blob removed, no orphans


# ── cutoff direction: an ancient cutoff matches nothing ───────────────────────


def test_prune_ancient_cutoff_removes_nothing(store, tmp_path):
    _seed_full(store, tmp_path)
    before = _counts(store)
    result = store.run("prune", "--before", _ANCIENT)
    assert result.returncode == 0, result.stderr
    assert _counts(store) == before


# ── argument + store-access contract ──────────────────────────────────────────


def test_prune_requires_before(store):
    store.init()
    result = store.run("prune")
    assert result.returncode == 2, result.stderr


def test_prune_relative_before_offset_parses(store, tmp_path):
    # `--before -30d` (a leading-dash relative offset) must parse as a value.
    _seed_full(store, tmp_path)
    result = store.run("prune", "--before", "-30d")
    assert result.returncode == 0, result.stderr  # nothing that old; just succeeds


def test_prune_uninitialized_exits_5(store):
    result = store.run("prune", "--before", "-30d")
    assert result.returncode == 5, result.stderr


def test_prune_locked_exits_3(store, tmp_path):
    _seed_full(store, tmp_path)
    result = store.run("prune", "--before", "-30d", passphrase=None)
    assert result.returncode == 3, result.stderr
