"""``norm record`` — capture screenshots + AX trees on the timed loop.

This iteration implements the single-shot path, ``record --once``: the capture
engine that the persistent loop and launchd lifecycle (RECORD-005/006/009) will
drive in a later iteration. One tick is:

1. **preflight** — environment first (permissions + macapptree, exit 6) so it
   precedes auth, then unlock the store (exit 3) (conventions.exit_precedence);
2. **idle gate** — if idle ≥ ``idle_threshold`` skip the shot and buffer the idle
   seconds for the next stored capture (RECORD-002);
3. **dedupe gate** — capture, hash, and if the frame matches the last stored one on
   *both* phash and AX, extend that row's ``duration_s`` instead of storing
   (RECORD-003); a change in either signal stores a new frame (RECORD-004);
4. **store** — write the image and AX as encrypted blobs and one capture row
   (RECORD-001, REQ-SEC-001).

Capture inputs and the host probes are isolated in :mod:`norm.capture` (with the
hidden test seams); the dedupe math is in :mod:`norm.hashing`.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from norm import blobs, capture, config as config_mod, errors, hashing, session
from norm import store as store_mod

# Buffered wall-clock idle, carried in the index meta table between ticks and stamped
# on the next stored capture as idle_gap_s (RECORD-002).
_PENDING_IDLE_KEY = "pending_idle_s"


def configure(parser: argparse.ArgumentParser) -> None:
    """Attach record's flags and handler. Capture-tuning flags override config + default."""
    parser.add_argument("--once", action="store_true", help="Capture a single frame and exit.")
    parser.add_argument("--interval", dest="interval_minutes", type=int, metavar="MINUTES",
                        help="Minutes accounted to each capture (config: interval_minutes).")
    parser.add_argument("--idle-threshold", dest="idle_threshold_seconds", type=int, metavar="SECONDS",
                        help="Idle seconds above which a tick is skipped (config: idle_threshold_seconds).")
    parser.add_argument("--phash-threshold", dest="phash_threshold", type=int, metavar="N",
                        help="Max phash Hamming distance still treated as unchanged (config: phash_threshold).")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    if not args.once:
        # The persistent loop and launchd lifecycle land with RECORD-005/006/009.
        print("norm record: the persistent loop is not implemented yet; use --once", file=sys.stderr)
        return int(errors.ExitCode.RUNTIME_ERROR)

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
    try:
        return _capture_once(con, data_key, paths, interval_s, idle_threshold, phash_threshold)
    finally:
        con.close()


def _capture_once(con, data_key, paths, interval_s, idle_threshold, phash_threshold) -> int:
    idle = capture.read_idle_seconds()
    if idle >= idle_threshold:
        _buffer_idle(con, idle)
        store_mod.flush_index(con, paths.index_file, data_key)
        print(f"idle {int(idle)}s; skipped")
        return int(errors.ExitCode.SUCCESS)

    frame = capture.capture_frame()
    new_phash = hashing.phash(frame.image)
    new_ax_hash = hashing.ax_hash(frame.ax)

    last = store_mod.last_capture(con)
    if last and hashing.is_duplicate(
        new_phash, new_ax_hash, last["phash"], last["ax_hash"], threshold=phash_threshold
    ):
        store_mod.extend_duration(con, last["id"], interval_s)
        store_mod.flush_index(con, paths.index_file, data_key)
        print(f"duplicate; extended capture {last['id']} (+{interval_s}s)")
        return int(errors.ExitCode.SUCCESS)

    capture_id = _store_frame(con, data_key, paths, frame, new_phash, new_ax_hash, interval_s)
    store_mod.flush_index(con, paths.index_file, data_key)
    print(f"stored capture {capture_id}")
    return int(errors.ExitCode.SUCCESS)


def _buffer_idle(con, idle: float) -> None:
    """Accumulate idle into the pending gap (RECORD-002).

    HIDIdleTime is cumulative since the last input, so the largest value observed
    within an inter-capture gap is the best lower bound on idle time; taking the max
    (rather than summing overlapping observations) keeps idle_gap_s ≥ the observed idle.
    """
    prior = int(store_mod.get_meta(con, _PENDING_IDLE_KEY, "0"))
    store_mod.set_meta(con, _PENDING_IDLE_KEY, str(max(prior, int(idle))))


def _store_frame(con, data_key, paths, frame, new_phash, new_ax_hash, interval_s) -> int:
    """Write the encrypted blobs and the capture row; drain the buffered idle gap."""
    blobs_dir = paths.data_dir / session.BLOBS_DIR
    # Blobs first: an interrupted write leaves an orphan file, never a row that
    # references a missing blob (the flushed index is the source of truth).
    image_ref = blobs.write_blob(blobs_dir, data_key, frame.image_png)
    ax_ref = blobs.write_blob(blobs_dir, data_key, frame.ax_json)

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
