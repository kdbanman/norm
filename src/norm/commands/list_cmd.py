"""``norm list`` — show captures in a time range (REQ-DATA-002, concept §10.13).

Reads index metadata only (no blob decrypt). Requires an unlockable store, so it
surfaces the NOT_INITIALIZED / STORE_LOCKED contract (REQ-GLOBAL-007/008) and the
time-range semantics (REQ-GLOBAL-009) via :mod:`norm.timerange`.
"""

from __future__ import annotations

import argparse
import json

from norm import errors, session, store, timerange


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from", dest="frm", metavar="WHEN", help="Range start (ISO-8601 / relative / calendar word).")
    parser.add_argument("--to", dest="to", metavar="WHEN", help="Range end (defaults to now).")
    parser.add_argument("--last", dest="last", metavar="DURATION", help="A window ending now, e.g. 24h, 7d.")
    timerange.allow_relative_time_values(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    # Parse the range first: a bad combination is a usage error (exit 2), which
    # precedes the store-access checks.
    window = timerange.parse_range(frm=args.frm, to=args.to, last=args.last)

    paths = session.resolve_paths(args)
    con, _ = session.open_store(paths)
    try:
        start = timerange.to_db_ts(window.start) if window.start else None
        end = timerange.to_db_ts(window.end) if window.end else None
        rows = store.list_captures(con, start, end)
    finally:
        con.close()

    if getattr(args, "json", False):
        print(json.dumps(rows))
    else:
        _print_table(rows)
    return int(errors.ExitCode.SUCCESS)


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("(no captures)")
        return
    header = f"{'ID':>6}  {'TIMESTAMP':<19}  {'APP':<24}  {'IDLE_S':>7}  {'DUR_S':>6}"
    print(header)
    for row in rows:
        print(
            f"{row['id']:>6}  {row['ts']:<19}  {(row['active_app'] or ''):<24}  "
            f"{row['idle_gap_s']:>7}  {row['duration_s']:>6}"
        )
