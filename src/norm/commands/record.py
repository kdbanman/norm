"""``norm record`` — capture screenshots + AX trees on the timed loop.

``record`` runs the same capture *tick* either once (``--once``) or on a
persistent foreground loop (the default, RECORD-005). One tick is:

1. **preflight** — environment first (permissions + macapptree, exit 6) so it
   precedes auth, then unlock the store (exit 3) (conventions.exit_precedence);
2. **idle gate** — if idle ≥ ``idle_threshold`` skip the shot and buffer the idle
   seconds for the next stored capture (RECORD-002);
3. **dedupe gate** — capture, hash, and if the frame matches the last stored one on
   *both* phash and AX, extend that row's ``duration_s`` instead of storing
   (RECORD-003); a change in either signal stores a new frame (RECORD-004);
4. **store** — write the image and AX as encrypted blobs and one capture row
   (RECORD-001, REQ-SEC-001).

The loop runs a tick, then waits ``--interval`` minutes (interruptibly) before the
next, until SIGINT/SIGTERM; on signal it flushes, locks the store, and zeroes the
data key (RECORD-006). The unwrapped key is held in a ``bytearray`` for exactly
that reason — so :func:`norm.crypto.scrub` can zero it on exit rather than leave it
resident for the life of a long-running process.

Capture inputs and the host probes are isolated in :mod:`norm.capture` (with the
hidden test seams); the dedupe math is in :mod:`norm.hashing`.

Hidden, test-only seams (never product features — see norm-requirements
verification.seam_note) make the otherwise-endless loop observable:

* ``NORM_FAKE_MAX_TICKS=<N>`` — stop cleanly after N ticks (RECORD-005);
* ``NORM_FAKE_SLEEP_LOG=<path>`` — record the interval each wait *would* sleep and
  nap only briefly, so loop tests run fast and the cadence is inspectable.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from contextlib import contextmanager
from datetime import datetime

from norm import blobs, capture, config as config_mod, crypto, errors, hashing, session
from norm import store as store_mod

# Buffered wall-clock idle, carried in the index meta table between ticks and stamped
# on the next stored capture as idle_gap_s (RECORD-002).
_PENDING_IDLE_KEY = "pending_idle_s"

# Test-only loop seams (see module docstring).
ENV_MAX_TICKS = "NORM_FAKE_MAX_TICKS"
ENV_SLEEP_LOG = "NORM_FAKE_SLEEP_LOG"
# In NORM_FAKE_SLEEP_LOG mode the loop naps this long instead of the real interval,
# so tests run fast without a hot spin (still interruptible by the stop event).
_TEST_NAP_S = 0.01


def configure(parser: argparse.ArgumentParser) -> None:
    """Attach record's flags and handler. Capture-tuning flags override config + default."""
    parser.add_argument("--once", action="store_true", help="Capture a single frame and exit.")
    parser.add_argument("--interval", dest="interval_minutes", type=int, metavar="MINUTES",
                        help="Minutes between captures, also accounted to each capture "
                             "(config: interval_minutes).")
    parser.add_argument("--idle-threshold", dest="idle_threshold_seconds", type=int, metavar="SECONDS",
                        help="Idle seconds above which a tick is skipped (config: idle_threshold_seconds).")
    parser.add_argument("--phash-threshold", dest="phash_threshold", type=int, metavar="N",
                        help="Max phash Hamming distance still treated as unchanged (config: phash_threshold).")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    paths = session.resolve_paths(args)
    cfg = session.load_config(paths)
    interval_s = int(config_mod.effective_value("interval_minutes", args.interval_minutes, cfg)) * 60
    idle_threshold = int(config_mod.effective_value("idle_threshold_seconds", args.idle_threshold_seconds, cfg))
    phash_threshold = int(config_mod.effective_value("phash_threshold", args.phash_threshold, cfg))

    # Failure precedence: not-initialized (5) → environment (6) → auth (3).
    if not session.is_initialized(paths):
        raise errors.not_initialized("store not initialized; run `norm init`")
    capture.ensure_available()
    con, data_key = session.open_store(paths)
    # Hold the key in a mutable buffer so shutdown can zero it (RECORD-006); the
    # immutable `bytes` from unwrap can't be scrubbed, so drop it right away.
    key = bytearray(data_key)
    del data_key
    try:
        if args.once:
            print(_tick(con, key, paths, interval_s, idle_threshold, phash_threshold))
            return int(errors.ExitCode.SUCCESS)
        return _record_loop(con, key, paths, interval_s, idle_threshold, phash_threshold)
    finally:
        # Lock the store and zero the key, for both the loop and one-shot paths.
        con.close()
        crypto.scrub(key)


def _tick(con, key, paths, interval_s, idle_threshold, phash_threshold) -> str:
    """Run one capture tick (idle/dedupe/store gate) and return a status line.

    Flushes the index before returning, so an interrupt after any tick leaves a
    consistent store (RECORD-006).
    """
    idle = capture.read_idle_seconds()
    if idle >= idle_threshold:
        _buffer_idle(con, idle)
        store_mod.flush_index(con, paths.index_file, key)
        return f"idle {int(idle)}s; skipped"

    frame = capture.capture_frame()
    new_phash = hashing.phash(frame.image)
    new_ax_hash = hashing.ax_hash(frame.ax)

    last = store_mod.last_capture(con)
    if last and hashing.is_duplicate(
        new_phash, new_ax_hash, last["phash"], last["ax_hash"], threshold=phash_threshold
    ):
        store_mod.extend_duration(con, last["id"], interval_s)
        store_mod.flush_index(con, paths.index_file, key)
        return f"duplicate; extended capture {last['id']} (+{interval_s}s)"

    capture_id = _store_frame(con, key, paths, frame, new_phash, new_ax_hash, interval_s)
    store_mod.flush_index(con, paths.index_file, key)
    return f"stored capture {capture_id}"


def _record_loop(con, key, paths, interval_s, idle_threshold, phash_threshold) -> int:
    """Run ticks every ``interval_s`` in the foreground until SIGINT/SIGTERM.

    Returns exit 0 on a clean stop. Each tick flushes the index; the wait between
    ticks wakes immediately when a signal sets the stop event, so shutdown is
    prompt regardless of the interval (RECORD-005/006).
    """
    stop = threading.Event()
    max_ticks = _env_int(ENV_MAX_TICKS)
    ticks = 0
    with _stop_on_signals(stop):
        while not stop.is_set():
            print(_tick(con, key, paths, interval_s, idle_threshold, phash_threshold), flush=True)
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            _interval_wait(interval_s, stop)
    if stop.is_set():  # stopped by signal, not by the max-ticks test seam
        print("record: stopped", file=sys.stderr)
    return int(errors.ExitCode.SUCCESS)


@contextmanager
def _stop_on_signals(stop: threading.Event):
    """Install SIGINT/SIGTERM handlers that request a clean stop, then restore them.

    Without this, SIGTERM would kill the process mid-write and SIGINT would surface
    as a traceback (exit 1); instead both set ``stop`` so the loop drains and exits 0.
    """
    def handler(_signum, _frame):
        stop.set()

    previous = {sig: signal.signal(sig, handler) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for sig, prev in previous.items():
            signal.signal(sig, prev)


def _interval_wait(interval_s: int, stop: threading.Event) -> None:
    """Wait ``interval_s`` before the next tick, returning early if ``stop`` is set.

    Under the ``NORM_FAKE_SLEEP_LOG`` seam the real interval is recorded (not slept)
    and the loop naps briefly instead, so tests observe the cadence without waiting.
    """
    log = os.environ.get(ENV_SLEEP_LOG)
    if log:
        with open(log, "a") as fh:
            fh.write(f"{interval_s}\n")
        stop.wait(_TEST_NAP_S)
    else:
        stop.wait(interval_s)


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    return int(value) if value else None


def _buffer_idle(con, idle: float) -> None:
    """Accumulate idle into the pending gap (RECORD-002).

    HIDIdleTime is cumulative since the last input, so the largest value observed
    within an inter-capture gap is the best lower bound on idle time; taking the max
    (rather than summing overlapping observations) keeps idle_gap_s ≥ the observed idle.
    """
    prior = int(store_mod.get_meta(con, _PENDING_IDLE_KEY, "0"))
    store_mod.set_meta(con, _PENDING_IDLE_KEY, str(max(prior, int(idle))))


def _store_frame(con, key, paths, frame, new_phash, new_ax_hash, interval_s) -> int:
    """Write the encrypted blobs and the capture row; drain the buffered idle gap."""
    blobs_dir = paths.data_dir / session.BLOBS_DIR
    # Blobs first: an interrupted write leaves an orphan file, never a row that
    # references a missing blob (the flushed index is the source of truth).
    image_ref = blobs.write_blob(blobs_dir, key, frame.image_png)
    ax_ref = blobs.write_blob(blobs_dir, key, frame.ax_json)

    idle_gap_s = int(store_mod.get_meta(con, _PENDING_IDLE_KEY, "0"))
    capture_id = store_mod.insert_capture(
        con,
        ts=datetime.now().isoformat(timespec="seconds"),
        active_app=frame.active_app,
        idle_gap_s=idle_gap_s,
        phash=new_phash,
        ax_hash=new_ax_hash,
        image_ref=image_ref,
        ax_ref=ax_ref,
        duration_s=interval_s,
    )
    store_mod.set_meta(con, _PENDING_IDLE_KEY, "0")
    return capture_id
