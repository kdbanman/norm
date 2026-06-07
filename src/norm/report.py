"""Window planning + coverage identity for the report pipeline (concept §10.8–10.12).

Pure, below-the-CLI logic shared by ``report preprocess`` and ``report interval``:
slice the time-ordered captures into the K-wide, stride-J windows the model
summarizes, and give each window the stable identity used to decide whether an
existing preprocess row already covers it. Kept independent of the store and the
model so the window/stride math (PREPROCESS-001) is unit-testable on plain dicts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from norm import errors


@dataclass(frozen=True)
class Window:
    """One summarization window: the ordered capture ids it spans and their ts bounds."""

    capture_ids: tuple[int, ...]
    start: str
    end: str


def canonical_ids(capture_ids: tuple[int, ...] | list[int]) -> str:
    """The window's identity key: its ordered capture ids as a canonical JSON array.

    A window is identified by its *ordered* capture-id set (PREPROCESS-003); this is
    the exact string stored in ``preprocess.capture_ids`` and matched on re-run, so
    serialization must be identical on write and lookup.
    """
    return json.dumps(list(capture_ids), separators=(",", ":"))


def plan_windows(captures: list[dict], window_k: int, stride_j: int) -> list[Window]:
    """Slide a ``window_k``-wide window with stride ``stride_j`` over ``captures``.

    ``captures`` are dicts with ``id`` and ``ts``, already ordered by ts. Returns
    ``floor((N - K) / J) + 1`` windows; trailing remainder captures that don't fill a
    full window are dropped (summarized by a later run). Raises NO_CAPTURES (no
    captures) or NOT_ENOUGH_CAPTURES (``0 < N < K``), both exit 5; a non-positive
    window or stride is a usage error.
    """
    if window_k < 1 or stride_j < 1:
        raise errors.usage_error("--window and --stride must be >= 1")
    n = len(captures)
    if n == 0:
        raise errors.no_captures("no captures to process; run `norm record` first")
    if n < window_k:
        raise errors.not_enough_captures(
            f"only {n} capture(s); need at least --window={window_k} for one window"
        )
    count = (n - window_k) // stride_j + 1
    windows: list[Window] = []
    for w in range(count):
        chunk = captures[w * stride_j : w * stride_j + window_k]
        windows.append(Window(tuple(c["id"] for c in chunk), chunk[0]["ts"], chunk[-1]["ts"]))
    return windows
