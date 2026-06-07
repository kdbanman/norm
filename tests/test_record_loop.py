"""Black-box acceptance tests for the persistent ``norm record`` loop.

Covers RECORD-005 (foreground loop honoring ``--interval``) and RECORD-006
(clean shutdown on SIGINT/SIGTERM). The loop runs forever by design, so two
hidden, test-only seams (never product features — see norm-requirements
verification.seam_note) make it observable without waiting real minutes:

* ``NORM_FAKE_MAX_TICKS=<N>`` — stop cleanly after N capture ticks, so a
  foreground run terminates deterministically for assertion;
* ``NORM_FAKE_SLEEP_LOG=<path>`` — the inter-tick wait records the interval it
  *would* sleep (one value per line) and naps only briefly, so the loop runs fast
  and its cadence is inspectable.

The capture itself still goes through the ``NORM_FAKE_CAPTURE`` seam, so no real
screen, macapptree, or model is involved.
"""

from __future__ import annotations

import json
import signal
import time
from pathlib import Path

import pytest

from tools.normdev.harness import capture_env, write_fake_frame


def _captures(store):
    result = store.run("list", "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _loop_env(frame: str, *, max_ticks: int | None, sleep_log: Path, idle: str = "0") -> dict:
    env = capture_env(frame, idle=idle)
    env["NORM_FAKE_SLEEP_LOG"] = str(sleep_log)
    if max_ticks is not None:
        env["NORM_FAKE_MAX_TICKS"] = str(max_ticks)
    return env


# ── RECORD-005: foreground loop honoring --interval ──────────────────────────────


def test_record_loop_iterates_and_honors_interval(store, tmp_path):
    """`record --interval 2` loops in the foreground, ~every interval, until stopped.

    Same frame each tick ⇒ the dedupe path extends one row by interval_s per tick,
    so the final duration proves the loop actually iterated N times; the sleep log
    proves each inter-tick wait used the configured interval (not ignored).
    """
    store.init()
    frame = write_fake_frame(tmp_path / "f")
    sleep_log = tmp_path / "sleeps.log"

    result = store.run(
        "record", "--interval", "2",
        extra_env=_loop_env(frame, max_ticks=3, sleep_log=sleep_log),
    )
    assert result.returncode == 0, result.stderr

    rows = _captures(store)
    assert len(rows) == 1  # same frame deduped into one row...
    assert rows[0]["duration_s"] == 360  # ...extended 3× by interval_s (3 * 120)

    waited = [ln.strip() for ln in sleep_log.read_text().splitlines() if ln.strip()]
    assert waited, "loop exited without ever waiting the interval"
    assert all(w == "120" for w in waited)  # every wait used --interval 2 (120s)


def test_record_no_once_runs_the_capture_engine_not_a_stub(store, tmp_path):
    """Without --once, record drives the real capture engine (not the old stub)."""
    store.init()
    frame = write_fake_frame(tmp_path / "f", app="Safari")
    sleep_log = tmp_path / "sleeps.log"

    result = store.run(
        "record", "--interval", "1",
        extra_env=_loop_env(frame, max_ticks=1, sleep_log=sleep_log),
    )
    assert result.returncode == 0, result.stderr
    rows = _captures(store)
    assert len(rows) == 1
    assert rows[0]["active_app"] == "Safari"
    assert rows[0]["duration_s"] == 60


# ── RECORD-006: clean shutdown on SIGINT/SIGTERM ─────────────────────────────────


def _wait_for_first_tick(store, sleep_log: Path, timeout: float = 15.0):
    """Block until the loop has run at least one tick (a capture is flushed)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _captures(store):
            return
        time.sleep(0.05)
    raise AssertionError("record loop never produced a capture")


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_record_loop_shuts_down_cleanly_on_signal(store, tmp_path, sig):
    """A running loop, on SIGINT/SIGTERM, flushes, exits 0, and leaves a sound store."""
    store.init()
    frame = write_fake_frame(tmp_path / "f")
    sleep_log = tmp_path / "sleeps.log"
    # No max-ticks: the loop runs until we signal it.
    env = _loop_env(frame, max_ticks=None, sleep_log=sleep_log)

    proc = store.popen("record", "--interval", "1", extra_env=env)
    try:
        _wait_for_first_tick(store, sleep_log)
        proc.send_signal(sig)
        out, err = proc.communicate(timeout=15)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()

    assert proc.returncode == 0, f"non-zero exit on {sig!r}: {err}"
    assert "Traceback" not in err, err  # graceful stop, not an unhandled signal

    # Store is consistent: the in-flight capture was flushed and reads back fine.
    rows = _captures(store)
    assert len(rows) >= 1
    # ...and the store is still usable afterward (not left locked/corrupt).
    assert store.run("status", "--json").returncode == 0
