"""Unit tests for time-range parsing (REQ-GLOBAL-009), below the CLI.

The CLI tests assert exit codes; these pin the resolution semantics directly:
mutual exclusion of --last with --from/--to, --to defaulting to now, relative
offsets on both ends, ISO-8601, calendar words, and the require_range guard used
by `report interval`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from norm import errors, timerange

# A fixed "now" in a fixed offset so assertions are deterministic.
NOW = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone(timedelta(hours=-6)))


def test_last_with_from_is_usage_error():
    with pytest.raises(errors.NormError) as ei:
        timerange.parse_range(frm="-1h", last="24h", now=NOW)
    assert ei.value.exit_code == errors.ExitCode.USAGE_ERROR


def test_last_with_to_is_usage_error():
    with pytest.raises(errors.NormError):
        timerange.parse_range(to="now", last="24h", now=NOW)


def test_last_resolves_to_window_ending_now():
    r = timerange.parse_range(last="24h", now=NOW)
    assert r.end == NOW
    assert r.start == NOW - timedelta(hours=24)


def test_only_from_defaults_end_to_now():
    r = timerange.parse_range(frm="-1h", now=NOW)
    assert r.start == NOW - timedelta(hours=1)
    assert r.end == NOW


def test_relative_offsets_on_both_ends():
    r = timerange.parse_range(frm="-24h", to="-1h", now=NOW)
    assert r.start == NOW - timedelta(hours=24)
    assert r.end == NOW - timedelta(hours=1)


def test_no_range_is_unbounded():
    r = timerange.parse_range(now=NOW)
    assert r.start is None and r.end is None


def test_require_range_raises_when_unbounded():
    with pytest.raises(errors.NormError) as ei:
        timerange.parse_range(now=NOW, require_range=True)
    assert ei.value.exit_code == errors.ExitCode.USAGE_ERROR


def test_iso_8601_parsed_in_local_tz():
    r = timerange.parse_range(frm="2026-01-01T00:00:00", to="2026-01-02T00:00:00", now=NOW)
    assert r.start.year == 2026 and r.start.month == 1 and r.start.day == 1
    # naive ISO inherits the now-relative offset
    assert r.start.utcoffset() == NOW.utcoffset()


def test_now_keyword():
    r = timerange.parse_range(frm="-1h", to="now", now=NOW)
    assert r.end == NOW


def test_yesterday_is_whole_prior_local_day():
    r = timerange.parse_range(frm="yesterday", now=NOW)
    midnight_today = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    assert r.start == midnight_today - timedelta(days=1)
    assert r.end == midnight_today  # [00:00, 24:00) of the prior day


def test_invalid_value_is_usage_error():
    with pytest.raises(errors.NormError) as ei:
        timerange.parse_range(frm="garbage", now=NOW)
    assert ei.value.exit_code == errors.ExitCode.USAGE_ERROR


def test_to_db_ts_is_naive_local_iso_seconds():
    ts = timerange.to_db_ts(NOW)
    assert ts == "2026-06-06T12:00:00"


def test_to_db_ts_preserves_sub_second_so_now_end_includes_current_second():
    # A live `now` carrying microseconds must sort after a same-second capture ts,
    # so the half-open `[start, now)` end still covers captures recorded this second.
    live = NOW.replace(microsecond=123456)
    assert timerange.to_db_ts(live) == "2026-06-06T12:00:00.123456"
    assert "2026-06-06T12:00:00" < timerange.to_db_ts(live)
