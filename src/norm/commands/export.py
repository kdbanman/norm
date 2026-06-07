"""``norm export`` — decrypt a range of artifacts to a plaintext directory (REQ-DATA-005).

The range-scoped, all-types companion to ``show --export``: it decrypts every
requested artifact in ``[--from, --to)`` and writes plaintext under ``--out`` —

    --out/images/<id>.png
    --out/ax/<id>.ax.json
    --out/reports/preprocess/<window_id>.md
    --out/reports/interval/<report_id>.md

``--include`` selects a subset of ``images,ax,reports`` (default: all); ``reports``
covers BOTH preprocess summaries and interval reports (concept §10.15). This is the
sole user-requested exception to ciphertext-at-rest (REQ-SEC-001); decryption is
transient and in-memory and a type's directory is created only when it has at least
one artifact, so an empty range writes nothing. The store is unlocked before any
file is written, so a locked store fails (exit 3) having produced no plaintext.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from norm import artifacts, blobs, crypto, errors, session, timerange
from norm import store as store_mod


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from", dest="frm", metavar="WHEN", help="Range start.")
    parser.add_argument("--to", dest="to", metavar="WHEN", help="Range end (defaults to now).")
    parser.add_argument("--last", dest="last", metavar="DURATION",
                        help="A window ending now, e.g. 24h, 7d.")
    parser.add_argument("--out", dest="out", metavar="DIR", required=True,
                        help="Directory to write the decrypted artifacts into (plaintext).")
    parser.add_argument("--include", dest="include", metavar="TYPES",
                        help="Comma-separated subset of images,ax,reports (default: all).")
    timerange.allow_relative_time_values(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    # --include / range parsing are usage errors (exit 2) raised before store access.
    types = artifacts.parse_include(args.include)
    window = timerange.parse_range(frm=args.frm, to=args.to, last=args.last)

    paths = session.resolve_paths(args)
    con, data_key = session.open_store(paths)
    key = bytearray(data_key)
    try:
        start = timerange.to_db_ts(window.start) if window.start else None
        end = timerange.to_db_ts(window.end) if window.end else None
        out_dir = Path(args.out).expanduser()
        blobs_dir = paths.data_dir / session.BLOBS_DIR
        written = _export(con, key, blobs_dir, out_dir, types, start, end)
    finally:
        con.close()
        crypto.scrub(key)

    if getattr(args, "json", False):
        print(json.dumps({"out": str(out_dir), "written": written}))
    else:
        for kind in artifacts.ALL:
            if kind in written:
                print(f"{kind:<10}  {written[kind]}")
    return int(errors.ExitCode.SUCCESS)


def _export(con, key, blobs_dir: Path, out_dir: Path, types: set[str],
            start: str | None, end: str | None) -> dict[str, int]:
    """Decrypt the requested artifacts in range into ``out_dir``; return per-type counts."""
    written: dict[str, int] = {}
    if artifacts.IMAGES in types or artifacts.AX in types:
        written.update(_export_captures(con, key, blobs_dir, out_dir, types, start, end))
    if artifacts.REPORTS in types:
        written[artifacts.REPORTS] = _export_reports(con, key, blobs_dir, out_dir, start, end)
    return written


def _export_captures(con, key, blobs_dir, out_dir, types, start, end) -> dict[str, int]:
    """Write each in-range capture's requested image/AX blobs as decrypted files."""
    n_images = n_ax = 0
    for row in store_mod.captures_in_range(con, start, end):
        if artifacts.IMAGES in types:
            dest = _ensure(out_dir / artifacts.IMAGES) / f"{row['id']}.png"
            dest.write_bytes(blobs.read_blob(blobs_dir, key, row["image_ref"]))
            n_images += 1
        if artifacts.AX in types:
            dest = _ensure(out_dir / artifacts.AX) / f"{row['id']}.ax.json"
            dest.write_bytes(blobs.read_blob(blobs_dir, key, row["ax_ref"]))
            n_ax += 1
    counts = {}
    if artifacts.IMAGES in types:
        counts[artifacts.IMAGES] = n_images
    if artifacts.AX in types:
        counts[artifacts.AX] = n_ax
    return counts


def _export_reports(con, key, blobs_dir, out_dir, start, end) -> int:
    """Write in-range preprocess + interval markdown as decrypted ``.md`` files."""
    reports_dir = out_dir / artifacts.REPORTS
    count = 0
    for row in store_mod.preprocess_in_range(con, start, end):
        dest = _ensure(reports_dir / "preprocess") / f"{row['id']}.md"
        dest.write_bytes(blobs.read_blob(blobs_dir, key, row["markdown_ref"]))
        count += 1
    for row in store_mod.interval_reports_in_range(con, start, end):
        dest = _ensure(reports_dir / "interval") / f"{row['id']}.md"
        dest.write_bytes(blobs.read_blob(blobs_dir, key, row["markdown_ref"]))
        count += 1
    return count


def _ensure(directory: Path) -> Path:
    """Create ``directory`` (and parents) on first use, so empty types make no dir."""
    directory.mkdir(parents=True, exist_ok=True)
    return directory
