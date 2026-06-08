"""Unit tests for the real (non-seam) capture backend, :mod:`norm.capture`.

The record loop's *behaviour* is covered black-box via the ``NORM_FAKE_CAPTURE`` seam
(tests/test_record.py). These tests cover the real backend that the seam stands in for:

* the in-process composition glue — that ``_macapptree_frame`` assembles a :class:`Frame`
  from the native probes (frontmost app, AX tree + active-window bounds, screenshot) with
  the image bytes, decoded image, and AX JSON all consistent, and that the screenshot
  follows the display holding the active window (REQ-RECORD-010) — exercised
  deterministically by stubbing the probes;
* the pure display-selection geometry that maps a window's bounds to the display
  containing it (REQ-RECORD-010);
* the Screen-Recording-revoked failure mapping;
* a real end-to-end capture, which runs only where Screen Recording + Accessibility are
  granted on a live display and is skipped otherwise (REQ-RECORD-001, ENV-001, SEC-001).
"""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from norm import capture, errors

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_bytes(color=(10, 20, 30), size=(8, 6)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_macapptree_frame_composes_frame_from_probes(monkeypatch):
    """_macapptree_frame maps the native probes into a consistent Frame."""
    png = _png_bytes(size=(8, 6))
    ax = {"role": "AXWindow", "name": "Editor", "children": [{"role": "AXButton", "name": "OK"}]}
    monkeypatch.setattr(capture, "_frontmost_app", lambda: ("TextEdit", 4242))
    monkeypatch.setattr(capture, "_capture_ax_tree", lambda pid: (ax, None))
    monkeypatch.setattr(capture, "_screenshot_png", lambda display_id=None: png)

    frame = capture._macapptree_frame()

    assert isinstance(frame, capture.Frame)
    assert frame.active_app == "TextEdit"
    # The stored bytes are exactly the screenshot bytes; the image decodes from those bytes.
    assert frame.image_png == png
    assert frame.image.mode == "RGB"
    assert frame.image.size == (8, 6)
    # AX is carried as the dict and as its faithful JSON encoding.
    assert frame.ax == ax
    assert json.loads(frame.ax_json.decode("utf-8")) == ax


def test_macapptree_frame_tolerates_no_frontmost_app(monkeypatch):
    """No frontmost app → no pid to query → empty AX tree, screenshot still taken."""
    png = _png_bytes()
    monkeypatch.setattr(capture, "_frontmost_app", lambda: (None, None))
    monkeypatch.setattr(capture, "_screenshot_png", lambda display_id=None: png)
    # _capture_ax_tree must not be consulted when there is no pid.
    monkeypatch.setattr(
        capture, "_capture_ax_tree", lambda pid: pytest.fail("AX queried without a pid")
    )

    frame = capture._macapptree_frame()

    assert frame.active_app is None
    assert frame.ax == {}
    assert frame.ax_json == b"{}"
    assert frame.image_png == png


# ── REQ-RECORD-010: capture the display holding the active window ────────────────

# Two displays in the global (top-left origin) coordinate space: the main display at the
# origin and a secondary one to its right — the shape `CGDisplayBounds` reports.
_MAIN = (1, (0.0, 0.0, 1440.0, 900.0))
_SECONDARY = (3, (1440.0, 0.0, 1920.0, 1080.0))


def test_select_display_picks_display_containing_window():
    """A window on the secondary display selects that display, not the main one."""
    on_secondary = (1500.0, 100.0, 800.0, 600.0)  # center at (1900, 400) → secondary
    chosen = capture._select_display(on_secondary, [_MAIN, _SECONDARY], fallback_id=1)
    assert chosen == 3


def test_select_display_picks_main_when_window_on_main():
    on_main = (100.0, 100.0, 400.0, 300.0)  # center at (300, 250) → main
    chosen = capture._select_display(on_main, [_MAIN, _SECONDARY], fallback_id=1)
    assert chosen == 1


def test_select_display_falls_back_when_no_bounds():
    """Unknown window geometry → the main display (the safe default)."""
    assert capture._select_display(None, [_MAIN, _SECONDARY], fallback_id=1) == 1


def test_select_display_falls_back_when_center_off_all_displays():
    """A center in the gap between displays falls back rather than guessing."""
    in_gap = (5000.0, 5000.0, 10.0, 10.0)
    assert capture._select_display(in_gap, [_MAIN, _SECONDARY], fallback_id=1) == 1


def test_macapptree_frame_screenshots_active_windows_display(monkeypatch):
    """End-to-end glue: the AX-derived active-window bounds drive which display is shot.

    The screenshot is taken of the display holding the active window and the AX tree
    describes that same window — never unconditionally the main display (REQ-RECORD-010).
    """
    ax = {"role": "AXWindow", "name": "Editor"}
    window_on_secondary = (1500.0, 100.0, 800.0, 600.0)
    monkeypatch.setattr(capture, "_frontmost_app", lambda: ("Editor", 7))
    monkeypatch.setattr(capture, "_capture_ax_tree", lambda pid: (ax, window_on_secondary))
    monkeypatch.setattr(capture, "_online_display_bounds", lambda: [_MAIN, _SECONDARY])
    # CGMainDisplayID would say "1"; the active window is on "3".
    monkeypatch.setattr(capture, "_main_display_id", lambda: 1)

    shot_display: list[int] = []

    def fake_shot(display_id=None):
        shot_display.append(display_id)
        return _png_bytes()

    monkeypatch.setattr(capture, "_screenshot_png", fake_shot)

    frame = capture._macapptree_frame()

    assert shot_display == [3]  # the active window's display, not the main display
    assert frame.ax == ax  # …and the AX tree is that same window's


def test_screenshot_png_maps_revoked_capture_to_permission_error(monkeypatch):
    """A None from CGDisplayCreateImage (access revoked) → PERMISSION_MISSING (exit 6)."""
    Quartz = pytest.importorskip("Quartz")
    monkeypatch.setattr(Quartz, "CGDisplayCreateImage", lambda display_id: None)

    with pytest.raises(errors.NormError) as excinfo:
        capture._screenshot_png()

    assert excinfo.value.code == "PERMISSION_MISSING"
    assert excinfo.value.exit_code == errors.ExitCode.ENVIRONMENT_ERROR


def _real_capture_available() -> bool:
    """True iff a real screenshot can be taken here (perms granted, live display).

    Both grants are checked via their authoritative preflights:
    ``CGPreflightScreenCaptureAccess`` (not ``CGDisplayCreateImage``, which returns a *black*
    non-None image when Screen Recording is denied — see :func:`norm.capture._screenshot_png`)
    and ``AXIsProcessTrusted``.
    """
    try:
        import ApplicationServices
        import Quartz
    except Exception:
        return False
    return bool(
        ApplicationServices.AXIsProcessTrusted() and Quartz.CGPreflightScreenCaptureAccess()
    )


@pytest.mark.skipif(
    not _real_capture_available(),
    reason="needs Screen Recording + Accessibility granted on a live display",
)
def test_real_capture_smoke():
    """A genuine in-process capture yields a decodable PNG and a JSON-able AX dict."""
    frame = capture._macapptree_frame()

    assert frame.image_png[:8] == PNG_MAGIC
    Image.open(io.BytesIO(frame.image_png)).load()  # decodes without error
    assert frame.image.mode == "RGB"
    assert frame.image.size[0] > 0 and frame.image.size[1] > 0

    assert isinstance(frame.ax, dict)
    assert json.loads(frame.ax_json.decode("utf-8")) == frame.ax
    # active_app is a string on a normal GUI session; tolerate None on a headless one.
    assert frame.active_app is None or isinstance(frame.active_app, str)


@pytest.mark.skipif(
    not _real_capture_available(),
    reason="needs Screen Recording + Accessibility granted on a live display",
)
def test_real_active_display_id_is_online_and_matches_os_hit_test():
    """The selected display is a real online display, and for a point on it the OS agrees.

    Binds the pure selector (REQ-RECORD-010) to the native enumeration: every display the
    backend offers maps a point inside its own bounds back to itself via the OS hit-test
    (``CGGetDisplaysWithPoint``), so a window's center resolves to the display it sits on.
    """
    import Quartz

    displays = capture._online_display_bounds()
    assert displays, "a live display session must expose at least one online display"
    online_ids = {did for did, _ in displays}
    assert online_ids <= set(capture._cg_online_display_ids())

    for did, (x, y, w, h) in displays:
        center = (x + w / 2.0, y + h / 2.0)
        assert capture._select_display((x, y, w, h), displays, fallback_id=0) == did
        err, hit_ids, count = Quartz.CGGetDisplaysWithPoint(
            Quartz.CGPointMake(*center), 16, None, None
        )
        assert err == 0 and count >= 1
        assert did in set(list(hit_ids)[:count])
