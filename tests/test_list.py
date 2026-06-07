"""Black-box acceptance tests for `norm list` and the cross-cutting store-access
contracts it is the canonical vehicle for:

* REQ-DATA-002   — list shows captures in a range; --json is machine-readable.
* REQ-GLOBAL-007 — never-initialized store (exit 5, NOT_INITIALIZED) is distinct
                   from a present-but-locked store (exit 3, STORE_LOCKED).
* REQ-GLOBAL-008 — failures under --json emit {"error":{"code","exit","message"}}.
* REQ-GLOBAL-009 — time-range argument semantics (the list-applicable parts).

The store is empty after init (no `record` yet), so range *filtering over real
captures* is unit-tested below the CLI (tests/test_store.py); here we assert the
access contract, the JSON envelope/shape, and argument validation.
"""

from __future__ import annotations

import json


# ── REQ-GLOBAL-007: not-initialized vs locked ─────────────────────────────────


def test_list_uninitialized_exits_5_not_initialized(store):
    result = store.run("list")
    assert result.returncode == 5, result.stderr
    assert "init" in result.stderr.lower()


def test_list_locked_exits_3_store_locked(store):
    store.init()
    result = store.run("list", passphrase=None)
    assert result.returncode == 3, result.stderr
    assert "lock" in result.stderr.lower()


def test_list_uninitialized_json_envelope(store):
    result = store.run("--json", "list")
    assert result.returncode == 5
    env = json.loads(result.stdout)["error"]
    assert env["code"] == "NOT_INITIALIZED"
    assert env["exit"] == 5
    assert env["message"]


# ── REQ-GLOBAL-008: JSON error envelope with a stable code ─────────────────────


def test_list_locked_json_error_envelope(store):
    store.init()
    result = store.run("--json", "list", passphrase=None)
    assert result.returncode == 3
    env = json.loads(result.stdout)["error"]
    assert env["code"] == "STORE_LOCKED"
    assert env["exit"] == 3
    assert env["message"]


# ── REQ-DATA-002: list output ─────────────────────────────────────────────────


def test_list_empty_store_json_is_empty_array(store):
    store.init()
    result = store.run("list", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_list_empty_store_human_exit_zero(store):
    store.init()
    result = store.run("list")
    assert result.returncode == 0, result.stderr


def test_list_json_accepted_before_subcommand(store):
    store.init()
    result = store.run("--json", "list")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


# ── REQ-GLOBAL-009: time-range argument semantics ─────────────────────────────


def test_last_combined_with_from_is_usage_error(store):
    store.init()
    result = store.run("list", "--last", "24h", "--from", "-1h")
    assert result.returncode == 2, result.stderr


def test_last_combined_with_to_is_usage_error(store):
    store.init()
    result = store.run("list", "--last", "24h", "--to", "now")
    assert result.returncode == 2, result.stderr


def test_last_combined_with_from_json_envelope(store):
    store.init()
    result = store.run("--json", "list", "--last", "24h", "--from", "-1h")
    assert result.returncode == 2
    env = json.loads(result.stdout)["error"]
    assert env["code"] == "USAGE_ERROR"
    assert env["exit"] == 2


def test_relative_offsets_accepted_on_both_from_and_to(store):
    store.init()
    result = store.run("list", "--from", "-24h", "--to", "-1h")
    assert result.returncode == 0, result.stderr


def test_only_from_defaults_to_now(store):
    store.init()
    result = store.run("list", "--from", "-1h")
    assert result.returncode == 0, result.stderr


def test_no_range_lists_all(store):
    store.init()
    result = store.run("list")
    assert result.returncode == 0, result.stderr


def test_iso_8601_accepted(store):
    store.init()
    result = store.run("list", "--from", "2026-01-01T00:00:00", "--to", "2026-12-31T00:00:00")
    assert result.returncode == 0, result.stderr


def test_invalid_time_value_is_usage_error(store):
    store.init()
    result = store.run("list", "--from", "not-a-time")
    assert result.returncode == 2, result.stderr
