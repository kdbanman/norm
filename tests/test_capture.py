"""Unit tests for the real (non-seam) capture backend, :mod:`norm.capture`.

The record loop's *behaviour* is covered black-box via the ``NORM_FAKE_CAPTURE`` seam
(tests/test_record.py). These tests cover the real backend that the seam stands in for:

* the in-process composition glue — that ``_macapptree_frame`` assembles a :class:`Frame`
  from the three native probes (frontmost app, AX tree, screenshot) with the image bytes,
  decoded image, and AX JSON all consistent — exercised deterministically by stubbing the
  three probes;
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
    """_macapptree_frame maps the three native probes into a consistent Frame."""
    png = _png_bytes(size=(8, 6))
    ax = {"role": "AXWindow", "name": "Editor", "children": [{"role": "AXButton", "name": "OK"}]}
    monkeypatch.setattr(capture, "_frontmost_app", lambda: ("TextEdit", 4242))
    monkeypatch.setattr(capture, "_capture_ax_tree", lambda pid: ax)
    monkeypatch.setattr(capture, "_screenshot_png", lambda: png)

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
    monkeypatch.setattr(capture, "_screenshot_png", lambda: png)
    # _capture_ax_tree must not be consulted when there is no pid.
    monkeypatch.setattr(
        capture, "_capture_ax_tree", lambda pid: pytest.fail("AX queried without a pid")
    )

    frame = capture._macapptree_frame()

    assert frame.active_app is None
    assert frame.ax == {}
    assert frame.ax_json == b"{}"
    assert frame.image_png == png


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
