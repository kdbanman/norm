"""``norm prune`` — delete captures (and optionally summaries/reports) before a cutoff.

``prune --before <when>`` deletes every capture with ``ts < cutoff`` and unlinks its
image/AX blobs. Preprocess summaries and interval reports are RETAINED by default —
even when they now reference deleted captures — unless ``--include reports`` is
given, which additionally removes preprocess rows (``window_end < cutoff``) and
interval-report rows (``range_to < cutoff``) with their markdown blobs (REQ-DATA-006,
concept §10.16). ``--dry-run`` reports the would-remove counts and deletes nothing.

Deletion is ordered to forbid orphans on a completed run: the index rows are removed
and the encrypted index is flushed *before* any blob is unlinked, so an interruption
leaves at most a harmless orphan file — never a persisted row pointing at a missing
blob.
"""

from __future__ import annotations

import argparse
import json

from norm import artifacts, blobs, crypto, errors, session, timerange
from norm import store as store_mod


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--before", dest="before", metavar="WHEN", required=True,
                        help="Delete data older than this instant (e.g. -30d, 2026-01-01).")
    parser.add_argument("--include", dest="include", metavar="TYPES",
                        help="Also remove summaries/reports (only 'reports' is valid).")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Report what would be removed; delete nothing.")
    timerange.allow_relative_time_values(parser)  # accept `--before -30d`
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    # --include / cutoff parsing are usage errors (exit 2) raised before store access.
    include_reports = _wants_reports(args.include)
    cutoff = timerange.to_db_ts(timerange.parse_instant(args.before))

    paths = session.resolve_paths(args)
    con, data_key = session.open_store(paths)
    key = bytearray(data_key)
    try:
        captures = store_mod.captures_in_range(con, None, cutoff)
        preprocess = store_mod.preprocess_in_range(con, None, cutoff) if include_reports else []
        intervals = store_mod.interval_reports_in_range(con, None, cutoff) if include_reports else []
        counts = {
            "captures": len(captures),
            "preprocess": len(preprocess),
            "interval_reports": len(intervals),
        }
        if not args.dry_run:
            _delete(con, paths, key, captures, preprocess, intervals)
    finally:
        con.close()
        crypto.scrub(key)

    _emit(args, counts)
    return int(errors.ExitCode.SUCCESS)


def _wants_reports(include: str | None) -> bool:
    """Whether ``--include reports`` was given (the only type ``prune`` accepts)."""
    if include is None:
        return False
    return artifacts.REPORTS in artifacts.parse_include(include, allowed=(artifacts.REPORTS,))


def _delete(con, paths, key, captures, preprocess, intervals) -> None:
    """Remove the matched rows, flush the index, then unlink their blobs (no orphans)."""
    store_mod.delete_by_ids(con, "capture", [r["id"] for r in captures])
    store_mod.delete_by_ids(con, "preprocess", [r["id"] for r in preprocess])
    store_mod.delete_by_ids(con, "interval_report", [r["id"] for r in intervals])
    store_mod.flush_index(con, paths.index_file, key)

    blobs_dir = paths.data_dir / session.BLOBS_DIR
    for row in captures:
        blobs.delete_blob(blobs_dir, row["image_ref"])
        blobs.delete_blob(blobs_dir, row["ax_ref"])
    for row in (*preprocess, *intervals):
        blobs.delete_blob(blobs_dir, row["markdown_ref"])


def _emit(args: argparse.Namespace, counts: dict[str, int]) -> None:
    if getattr(args, "json", False):
        print(json.dumps({"dry_run": bool(args.dry_run), **counts}))
        return
    verb = "would remove" if args.dry_run else "removed"
    print(f"{verb} {counts['captures']} capture(s)")
    if counts["preprocess"] or counts["interval_reports"]:
        print(f"{verb} {counts['preprocess']} summary(ies), "
              f"{counts['interval_reports']} report(s)")
