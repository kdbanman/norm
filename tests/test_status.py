"""Black-box acceptance tests for `norm status` (REQ-DATA-001).

status is special: it must ALWAYS exit 0 and report store state — initialized,
locked/unlocked, data_dir, counts, daemon — reading counts from the encrypted
index without decrypting blobs.
"""

from __future__ import annotations

PASSPHRASE = "correct horse battery staple"


def test_status_uninitialized_reports_false_and_exits_zero(store):
    # No init has run: nothing under config_file / data_dir.
    result = store.run("status")
    assert result.returncode == 0, result.stderr
    assert "false" in result.stdout.lower() or "no" in result.stdout.lower()

    j = store.json_out(store.run("--json", "status"))
    assert j["initialized"] is False
    # exit code still 0 on a never-initialized machine.


def test_status_initialized_unlocked_reports_counts(store):
    store.init()
    result = store.run("status")
    assert result.returncode == 0, result.stderr
    out = result.stdout.lower()
    assert "unlock" in out  # "unlocked"
    assert "captures" in out or "capture" in out

    j = store.json_out(store.run("--json", "status"))
    assert j["initialized"] is True
    assert j["locked"] is False
    assert j["captures"] == 0
    assert j["last_capture"] is None
    assert j["preprocess"] == 0
    assert j["interval_reports"] == 0
    assert str(store.data_dir) in j["data_dir"]
    assert "daemon" in j  # daemon state is reported


def test_status_initialized_but_locked_never_fails(store):
    store.init()
    # No passphrase available and stdin closed: status must report locked, exit 0.
    result = store.run("status", passphrase=None)
    assert result.returncode == 0, result.stderr

    j = store.json_out(store.run("--json", "status", passphrase=None))
    assert j["initialized"] is True
    assert j["locked"] is True
    # Counts require the key; locked status leaves them unknown rather than failing.
    assert j["captures"] is None


def test_status_json_accepted_after_subcommand(store):
    """Global --json works both before and after the subcommand."""
    store.init()
    j = store.json_out(store.run("status", "--json"))
    assert j["initialized"] is True
