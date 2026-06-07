"""Parsing the ``--from`` / ``--to`` / ``--last`` time-range flags (REQ-GLOBAL-009).

Shared by every range-taking command (list, report, export, prune). One
:func:`parse_range` call resolves all three flags against a single
command-start ``now``, so relative offsets on either end agree.

Accepted forms (conventions.time_args):

* ISO-8601 — ``2026-06-06T09:30:00`` (naive values inherit ``now``'s tz);
* relative offset — ``-24h`` / ``-1h`` / ``7d`` (``s,m,h,d,w``; sign optional,
  default past) on ``--from``/``--to``;
* ``now`` — the command-start instant;
* calendar day words — ``yesterday`` / ``today`` expand to the whole local day
  ``[00:00, 24:00)`` (so ``--from yesterday`` alone covers all of yesterday);
* ``--last <duration>`` — a window ending at ``now``; mutually exclusive with
  ``--from``/``--to``.

Stored capture timestamps are local-naive ISO seconds; :func:`to_db_ts` renders a
range bound to that form for index queries.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from norm import errors

_OFFSET_RE = re.compile(r"^([+-]?)(\d+)([smhdw])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

# A relative-offset value (``-1h``, ``-30d``) starts with ``-``, so argparse would
# otherwise reject it as an unknown option. Widening the parser's "negative number"
# matcher to this pattern makes argparse treat such tokens as values instead.
_LEADING_DASH_VALUE = re.compile(r"^-\d+[smhdw]?$")


def allow_relative_time_values(parser: argparse.ArgumentParser) -> None:
    """Let a parser accept space-separated ``--from -1h`` style values.

    Call on any subparser carrying ``--from``/``--to``/``--last`` (REQ-GLOBAL-009).
    The subparsers have no numeric options, so broadening the matcher is safe.
    """
    parser._negative_number_matcher = _LEADING_DASH_VALUE  # noqa: SLF001


@dataclass(frozen=True)
class TimeRange:
    """A resolved ``[start, end)`` window; either bound may be ``None`` (unbounded)."""

    start: datetime | None
    end: datetime | None


def _parse_duration(text: str) -> timedelta:
    """Parse a bare positive duration like ``24h`` / ``7d`` (sign ignored)."""
    match = _OFFSET_RE.match(text.strip())
    if not match:
        raise errors.usage_error(f"invalid duration: {text!r} (use e.g. 24h, 7d)")
    _, number, unit = match.groups()
    return timedelta(seconds=int(number) * _UNIT_SECONDS[unit])


def _parse_instant(text: str, now: datetime) -> tuple[datetime, datetime | None]:
    """Resolve a single ``--from``/``--to`` value.

    Returns ``(instant, day_end)`` where ``day_end`` is non-None only for a
    calendar day word, carrying the implied end of that day so a lone
    ``--from yesterday`` can default ``--to`` to the day's end rather than ``now``.
    """
    token = text.strip().lower()
    if token == "now":
        return now, None
    if token in ("today", "yesterday"):
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if token == "yesterday":
            return midnight - timedelta(days=1), midnight
        return midnight, midnight + timedelta(days=1)

    match = _OFFSET_RE.match(token)
    if match:
        sign, number, unit = match.groups()
        delta = timedelta(seconds=int(number) * _UNIT_SECONDS[unit])
        return (now + delta if sign == "+" else now - delta), None

    try:
        instant = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise errors.usage_error(f"invalid time value: {text!r}") from exc
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=now.tzinfo)
    return instant, None


def parse_range(
    *,
    frm: str | None = None,
    to: str | None = None,
    last: str | None = None,
    now: datetime | None = None,
    require_range: bool = False,
) -> TimeRange:
    """Resolve the range flags into a :class:`TimeRange`.

    ``require_range=True`` (``report interval``) rejects an unbounded range as a
    usage error; otherwise an absent range means "everything" (``None, None``).
    """
    now = now or datetime.now().astimezone()

    if last is not None and (frm is not None or to is not None):
        raise errors.usage_error("--last cannot be combined with --from/--to")

    if last is not None:
        return TimeRange(now - _parse_duration(last), now)

    if frm is None and to is None:
        if require_range:
            raise errors.usage_error("a time range is required: use --from/--to or --last")
        return TimeRange(None, None)

    start: datetime | None = None
    end: datetime | None = None
    day_end: datetime | None = None
    if frm is not None:
        start, day_end = _parse_instant(frm, now)
    if to is not None:
        end, _ = _parse_instant(to, now)
    elif day_end is not None:
        end = day_end  # `--from yesterday` with no --to ⇒ end of that day
    elif frm is not None:
        end = now  # `--from` with no --to ⇒ up to now
    return TimeRange(start, end)


def to_db_ts(instant: datetime) -> str:
    """Render a range bound as a local-naive ISO string for index queries.

    Range bounds share ``now``'s offset, which is the local offset capture rows are
    stored in, so dropping the tz yields a value comparable to stored ``ts`` text.

    Sub-second precision is preserved (not truncated to whole seconds): captures are
    stored at second resolution, so a live ``now`` bound carrying microseconds sorts
    *after* any capture stamped in the current second. That keeps the half-open
    ``[start, end)`` end inclusive of the present second, so ``--last``/``--to now``
    still cover captures recorded in the same second the report runs. An explicit
    whole-second input (microsecond 0) renders without a fractional part, unchanged.
    """
    return instant.replace(tzinfo=None).isoformat()
