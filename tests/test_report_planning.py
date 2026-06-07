"""Unit tests for the report window planner (below the CLI).

The window/stride math (REQ-PREPROCESS-001) and the empty / too-few guards
(REQ-PREPROCESS-006/007) are pure logic, so they are tested directly here —
complementing the seam-driven black-box tests in ``tests/test_report.py``.
"""

from __future__ import annotations

import pytest

from norm import report
from norm.errors import ExitCode, NormError


def _captures(n: int) -> list[dict]:
    """``n`` capture rows with ids 1..n and monotonically increasing timestamps."""
    return [{"id": i, "ts": f"2026-06-06T10:{i:02d}:00"} for i in range(1, n + 1)]


# ── REQ-PREPROCESS-001: windows == floor((N - K) / J) + 1 ──────────────────────


@pytest.mark.parametrize(
    "n, k, j, expected",
    [
        (12, 6, 3, 3),  # concept §10.8 worked example
        (4, 2, 2, 2),
        (9, 6, 3, 2),
        (6, 6, 3, 1),  # exactly one window
        (7, 6, 3, 1),  # remainder capture dropped
        (10, 2, 2, 5),
    ],
)
def test_window_count_matches_formula(n, k, j, expected):
    windows = report.plan_windows(_captures(n), k, j)
    assert len(windows) == expected


def test_windows_carry_ordered_capture_ids_and_bounds():
    windows = report.plan_windows(_captures(4), window_k=2, stride_j=2)
    assert [w.capture_ids for w in windows] == [(1, 2), (3, 4)]
    assert windows[0].start == "2026-06-06T10:01:00"
    assert windows[0].end == "2026-06-06T10:02:00"


def test_stride_overlaps_windows():
    # K=3, J=1 over 5 captures → windows slide by one capture.
    windows = report.plan_windows(_captures(5), window_k=3, stride_j=1)
    assert [w.capture_ids for w in windows] == [(1, 2, 3), (2, 3, 4), (3, 4, 5)]


def test_trailing_remainder_is_dropped():
    # 7 captures, K=6, J=3 → one window of the first 6; capture 7 is left for later.
    windows = report.plan_windows(_captures(7), window_k=6, stride_j=3)
    assert len(windows) == 1
    assert windows[0].capture_ids == (1, 2, 3, 4, 5, 6)


# ── REQ-PREPROCESS-006 / -007: empty vs too-few ────────────────────────────────


def test_no_captures_raises_no_captures():
    with pytest.raises(NormError) as exc:
        report.plan_windows([], window_k=6, stride_j=3)
    assert exc.value.code == "NO_CAPTURES"
    assert exc.value.exit_code == ExitCode.NOT_FOUND


def test_fewer_than_one_window_raises_not_enough_captures():
    with pytest.raises(NormError) as exc:
        report.plan_windows(_captures(5), window_k=6, stride_j=3)
    assert exc.value.code == "NOT_ENOUGH_CAPTURES"
    assert exc.value.exit_code == ExitCode.NOT_FOUND


def test_invalid_window_or_stride_is_usage_error():
    with pytest.raises(NormError) as exc:
        report.plan_windows(_captures(4), window_k=0, stride_j=2)
    assert exc.value.exit_code == ExitCode.USAGE_ERROR
