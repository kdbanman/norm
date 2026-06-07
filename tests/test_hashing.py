"""Unit tests for the capture-gating math (RECORD-003 / RECORD-004).

These exercise the phash / normalized-AX hashing and the dedupe predicate directly,
below the CLI, as the verification plan calls for. The CLI-level black-box tests in
``test_record.py`` drive the same logic through ``record --once`` and the seams.
"""

from __future__ import annotations

from PIL import Image

from norm import hashing


def _gradient(width=64, height=64, *, vertical=False) -> Image.Image:
    img = Image.new("L", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = (y if vertical else x) * 255 // max(width, height)
    return img


# ── phash ────────────────────────────────────────────────────────────────────


def test_phash_is_stable_and_hex():
    img = _gradient()
    h1 = hashing.phash(img)
    h2 = hashing.phash(img.copy())
    assert h1 == h2
    assert isinstance(h1, str) and h1 == h1.lower()
    int(h1, 16)  # parses as hex


def test_phash_distance_zero_for_identical():
    img = _gradient()
    assert hashing.phash_distance(hashing.phash(img), hashing.phash(img.copy())) == 0


def test_phash_distance_small_for_minor_change():
    img = _gradient()
    nudged = img.point(lambda v: min(255, v + 3))  # slight brightness shift
    dist = hashing.phash_distance(hashing.phash(img), hashing.phash(nudged))
    assert dist <= 4


def test_phash_distance_large_for_different_image():
    horizontal = _gradient(vertical=False)
    vertical = _gradient(vertical=True)
    dist = hashing.phash_distance(hashing.phash(horizontal), hashing.phash(vertical))
    assert dist > 4


# ── ax_hash normalization ─────────────────────────────────────────────────────

_BASE_AX = {
    "role": "AXWindow",
    "title": "Editor",
    "position": {"x": 10, "y": 20},
    "size": {"width": 800, "height": 600},
    "focused": True,
    "children": [
        {"role": "AXButton", "title": "OK", "x": 12, "y": 640},
    ],
}


def test_ax_hash_stable():
    assert hashing.ax_hash(_BASE_AX) == hashing.ax_hash(dict(_BASE_AX))


def test_ax_hash_ignores_stripped_volatile_keys():
    variant = {
        "role": "AXWindow",
        "title": "Editor",
        "position": {"x": 10, "y": 20},
        "size": {"width": 800, "height": 600},
        "focused": False,  # focus toggled
        "selectedText": "hello",  # selection appeared
        "caret": 5,  # caret moved
        "scrollOffset": 120,  # scrolled
        "identifier": "ephemeral-9f3",  # ephemeral id
        "children": [
            {"role": "AXButton", "title": "OK", "x": 12, "y": 640},
        ],
    }
    assert hashing.ax_hash(variant) == hashing.ax_hash(_BASE_AX)


def test_ax_hash_ignores_subpixel_geometry_jitter():
    variant = {
        "role": "AXWindow",
        "title": "Editor",
        "position": {"x": 12, "y": 18},  # within the same coarse bucket
        "size": {"width": 790, "height": 610},
        "focused": True,
        "children": [
            {"role": "AXButton", "title": "OK", "x": 9, "y": 645},
        ],
    }
    assert hashing.ax_hash(variant) == hashing.ax_hash(_BASE_AX)


def test_ax_hash_changes_on_label_change():
    variant = dict(_BASE_AX, title="Browser")
    assert hashing.ax_hash(variant) != hashing.ax_hash(_BASE_AX)


def test_ax_hash_changes_on_role_change():
    variant = dict(_BASE_AX, role="AXSheet")
    assert hashing.ax_hash(variant) != hashing.ax_hash(_BASE_AX)


def test_ax_hash_changes_on_structure_change():
    variant = dict(_BASE_AX, children=[])
    assert hashing.ax_hash(variant) != hashing.ax_hash(_BASE_AX)


# ── dedupe predicate ───────────────────────────────────────────────────────────


def test_is_duplicate_requires_both_phash_and_ax():
    ph = "0011223344556677"
    ph_near = "0011223344556678"  # 1 bit off → within threshold
    ph_far = "ffffffffffffffff"
    ax = "a" * 64
    other_ax = "b" * 64
    # both match → duplicate
    assert hashing.is_duplicate(ph_near, ax, ph, ax, threshold=4)
    # ax differs → not a duplicate
    assert not hashing.is_duplicate(ph_near, other_ax, ph, ax, threshold=4)
    # phash too far → not a duplicate
    assert not hashing.is_duplicate(ph_far, ax, ph, ax, threshold=4)
