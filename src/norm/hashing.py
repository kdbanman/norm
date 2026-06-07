"""Capture-gating math: perceptual image hashing and normalized-AX hashing.

This is the dedupe heart of the recorder (concept §8). A frame is stored only when
the user is present *and* the screen changed; "changed" is decided here:

* :func:`phash` — a 64-bit dHash of the screenshot; :func:`phash_distance` is the
  Hamming distance between two such hashes. A small distance means "looks the same".
* :func:`ax_hash` — a SHA-256 over a *normalized projection* of the accessibility
  tree: structure, roles, labels, and coarse geometry buckets are kept; volatile
  state (focus, selection/caret, cursor, scroll offset, ephemeral ids) is stripped,
  so cosmetic AX churn doesn't count as a change. The strip-list defines "screen
  unchanged" for the AX side (concept §8 "Resolved details").
* :func:`is_duplicate` — the net rule: a frame dedupes only when its phash is within
  ``threshold`` of the previous frame **and** its ax_hash is identical (RECORD-003);
  a change in *either* signal stores a new frame (RECORD-004).

Kept deliberately below the CLI so it can be unit-tested directly (see
``tests/test_hashing.py``), independent of the seam-driven black-box tests.
"""

from __future__ import annotations

import hashlib
import json

import imagehash
from PIL import Image

# ── perceptual image hash ──────────────────────────────────────────────────────


def phash(image: Image.Image) -> str:
    """64-bit dHash of ``image`` as a 16-char hex string (concept §8)."""
    return str(imagehash.dhash(image))


def phash_distance(a: str, b: str) -> int:
    """Hamming distance between two :func:`phash` hex strings."""
    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)


# ── normalized AX-tree hash ─────────────────────────────────────────────────────

# Coarse geometry bucket (pixels): element positions/sizes are rounded to this grid
# so sub-bucket layout jitter is not treated as a screen change.
_GEOMETRY_BUCKET = 50

# Numeric geometry components, bucketed wherever they appear (coordinates/sizes).
_GEOMETRY_NUMBER_KEYS = {
    "x", "y", "w", "h", "width", "height", "left", "top", "right", "bottom",
}
# Containers that hold geometry as a list/tuple (e.g. "frame": [x, y, w, h]).
_GEOMETRY_LIST_KEYS = {"position", "size", "frame", "bounds", "rect", "absolute_position"}

# Volatile keys stripped before hashing: focus/selection/caret/cursor/scroll state
# and ephemeral identifiers. Matched case-insensitively against the key name. This
# strip-list *defines* "screen unchanged" for the AX side (concept §8).
_STRIP_KEYS = {
    "focused", "is_focused", "isfocused", "focus",
    "selected", "is_selected", "isselected",
    "selection", "selected_text", "selectedtext",
    "selected_text_range", "selectedtextrange",
    "caret", "insertion_point", "insertionpoint", "cursor",
    "scroll", "scroll_offset", "scrolloffset",
    "scroll_position", "scrollposition", "scrollbar",
    "identifier", "id", "element_id", "elementid",
    "uid", "uuid", "pid", "window_id", "windowid", "winid",
}


def _bucket(value: object) -> object:
    """Round a numeric geometry component to the coarse grid; pass non-numbers through."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(value / _GEOMETRY_BUCKET) * _GEOMETRY_BUCKET
    return value


def _normalize(node: object) -> object:
    """Project an AX node down to its stable shape (see module docstring)."""
    if isinstance(node, dict):
        out: dict = {}
        for key, value in node.items():
            lkey = key.lower()
            if lkey in _STRIP_KEYS:
                continue
            if lkey in _GEOMETRY_NUMBER_KEYS:
                out[key] = _bucket(value)
            elif lkey in _GEOMETRY_LIST_KEYS and isinstance(value, list):
                out[key] = [_bucket(v) for v in value]
            else:
                out[key] = _normalize(value)
        return out
    if isinstance(node, list):
        return [_normalize(item) for item in node]
    return node


def ax_hash(ax: object) -> str:
    """SHA-256 (hex) of the normalized AX projection."""
    canonical = json.dumps(_normalize(ax), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── net dedupe rule ─────────────────────────────────────────────────────────────


def is_duplicate(
    new_phash: str,
    new_ax_hash: str,
    last_phash: str,
    last_ax_hash: str,
    *,
    threshold: int,
) -> bool:
    """True iff the new frame should dedupe to the last one (RECORD-003).

    Requires *both* signals to match: phash within ``threshold`` Hamming distance and
    an identical ax_hash. A change in either stores a fresh frame (RECORD-004).
    """
    return new_ax_hash == last_ax_hash and phash_distance(new_phash, last_phash) <= threshold
