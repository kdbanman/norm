"""The capture backend: idle detection, permission/dependency preflight, and frames.

This is the only module that talks to the host's capture surfaces (concept §8). It
isolates three things the recorder needs and the rest of the code shouldn't know the
shape of:

* :func:`read_idle_seconds` — seconds since the last HID input (IOKit ``HIDIdleTime``).
* :func:`ensure_available` — the environment preflight: Screen Recording +
  Accessibility permission and the macapptree dependency must be present, else an
  ``ENVIRONMENT_ERROR`` (exit 6) *before* the store is unlocked (RECORD-007, ENV-001,
  conventions.exit_precedence).
* :func:`capture_frame` — one screenshot + AX tree as an in-memory :class:`Frame`.

Hidden, test-only seams (never product features — see norm-requirements
verification.seam_note) let the black-box tests drive this without a real screen:

* ``NORM_FAKE_IDLE=<seconds>`` — scripted idle for the idle gate (RECORD-002);
* ``NORM_FAKE_CAPTURE=<dir>`` — read ``image.png`` + ``ax.json`` (+ optional
  ``active_app.txt``) instead of macapptree (RECORD-001/003/004);
* ``NORM_FORCE_NO_PERMISSION=screen|ax`` — force a denied permission (RECORD-007);
* ``NORM_FORCE_NO_MACAPPTREE=1`` — force the dependency absent (ENV-001).

The real backend (:func:`_macapptree_frame`) captures in-process: the active display via
Quartz (in memory) and the frontmost app's AX tree via macapptree's ``UIElement`` — no temp
files, no ``screencapture`` / ``python -m macapptree.main`` subprocesses, and no focus change
(the frontmost app is read, never activated). The ``NORM_FAKE_CAPTURE`` seam still drives the
black-box tests without a real screen.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from norm import errors

# Seam env vars (test-only).
ENV_FAKE_IDLE = "NORM_FAKE_IDLE"
ENV_FAKE_CAPTURE = "NORM_FAKE_CAPTURE"
ENV_FORCE_NO_PERMISSION = "NORM_FORCE_NO_PERMISSION"
ENV_FORCE_NO_MACAPPTREE = "NORM_FORCE_NO_MACAPPTREE"


@dataclass
class Frame:
    """One capture: the decoded image + AX tree, plus the raw bytes to encrypt.

    ``image``/``ax`` feed the dedupe hashes (:mod:`norm.hashing`); ``image_png``/
    ``ax_json`` are the exact plaintext bytes the store encrypts at rest.
    """

    image: Image.Image
    image_png: bytes
    ax: dict
    ax_json: bytes
    active_app: str | None


# ── idle gate ───────────────────────────────────────────────────────────────────


def read_idle_seconds() -> float:
    """Seconds since the last HID input (concept §8 idle gate).

    Honors the ``NORM_FAKE_IDLE`` seam; otherwise reads IOKit ``HIDIdleTime`` via
    ``ioreg``. If the real read fails for any reason the user is treated as active
    (0.0) so a probe failure never silently suppresses capture.
    """
    fake = os.environ.get(ENV_FAKE_IDLE)
    if fake is not None:
        return float(fake)
    return _real_idle_seconds()


def _real_idle_seconds() -> float:
    try:
        out = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return 0.0
    for line in out.splitlines():
        if "HIDIdleTime" in line:
            # `... "HIDIdleTime" = 12345678` — value is in nanoseconds.
            try:
                nanos = int(line.rsplit("=", 1)[1].strip())
            except (IndexError, ValueError):
                return 0.0
            return nanos / 1_000_000_000
    return 0.0


# ── environment preflight ───────────────────────────────────────────────────────


def ensure_available() -> None:
    """Verify capture can run, or raise an ``ENVIRONMENT_ERROR`` (exit 6).

    Checks OS permissions then the capture backend, without taking a screenshot —
    callers run this before unlocking the store so an environment fault (6) takes
    precedence over an auth fault (3) (conventions.exit_precedence).
    """
    _check_permissions()
    _check_backend()


def _check_permissions() -> None:
    forced = os.environ.get(ENV_FORCE_NO_PERMISSION)
    if forced:
        label = {"screen": "Screen Recording", "ax": "Accessibility"}.get(forced, forced)
        raise errors.permission_missing(
            f"{label} permission not granted; enable norm under "
            "System Settings → Privacy & Security and retry"
        )
    # The real OS probe only applies when a real capture will actually run. Both capture
    # seams stand in for the real screen — NORM_FAKE_CAPTURE supplies frames, and
    # NORM_FORCE_NO_MACAPPTREE (ENV-001) forces the backend absent — so under either there
    # is nothing to probe. NORM_FORCE_NO_PERMISSION above still exercises the denied path
    # (RECORD-007); a genuine run (no seam) still hits the probe. Without this the probe
    # would fail in any environment lacking the grant, even one only driving the seams.
    if os.environ.get(ENV_FAKE_CAPTURE) or os.environ.get(ENV_FORCE_NO_MACAPPTREE):
        return
    _check_real_permissions()


def _check_real_permissions() -> None:
    """Best-effort real permission probe via the OS, when pyobjc is present.

    Screen Recording (``CGPreflightScreenCaptureAccess``) and Accessibility
    (``AXIsProcessTrusted``) are both checkable without prompting. When the
    frameworks aren't importable we can't probe, so we defer to the backend's own
    failure rather than block — the seam-driven test covers the denied path
    deterministically (RECORD-007).
    """
    try:
        from Quartz import CGPreflightScreenCaptureAccess  # type: ignore
    except Exception:
        pass
    else:
        if not CGPreflightScreenCaptureAccess():
            raise errors.permission_missing(
                "Screen Recording permission not granted; enable norm under "
                "System Settings → Privacy & Security and retry"
            )

    try:
        from ApplicationServices import AXIsProcessTrusted  # type: ignore
    except Exception:
        return
    if not AXIsProcessTrusted():
        raise errors.permission_missing(
            "Accessibility permission not granted; enable norm under "
            "System Settings → Privacy & Security and retry"
        )


def _check_backend() -> None:
    if os.environ.get(ENV_FAKE_CAPTURE):
        return  # faking the backend; macapptree is not consulted
    if os.environ.get(ENV_FORCE_NO_MACAPPTREE):
        raise errors.macapptree_missing(
            "macapptree is unavailable; capture cannot run (install macapptree)"
        )
    try:
        import macapptree  # noqa: F401
    except ImportError as exc:
        raise errors.macapptree_missing(
            "macapptree is not installed; capture cannot run (install macapptree)"
        ) from exc


# ── frame acquisition ───────────────────────────────────────────────────────────

# AX traversal depth. None = unbounded (macapptree's default): the captured tree is
# normalized downstream for the dedupe ax_hash (concept §8, ADR-004) and fed to the model
# as text, so the full tree is kept here rather than truncated at capture time.
_AX_MAX_DEPTH: int | None = None

# A rectangle ``(x, y, w, h)`` in the global, top-left-origin display coordinate space
# (the main display's top-left is the origin) — the space both AX positions and
# ``CGDisplayBounds`` report in, so window bounds and display bounds compare directly.
Bounds = tuple[float, float, float, float]

# An upper bound for CGGetOnlineDisplayList; far more displays than macOS supports.
_MAX_DISPLAYS = 16


def capture_frame() -> Frame:
    """Acquire one frame. Uses the ``NORM_FAKE_CAPTURE`` seam if set, else macapptree."""
    fake = os.environ.get(ENV_FAKE_CAPTURE)
    if fake:
        return _fake_frame(Path(fake))
    return _macapptree_frame()


def _fake_frame(dir_path: Path) -> Frame:
    image_png = (dir_path / "image.png").read_bytes()
    ax_json = (dir_path / "ax.json").read_bytes()
    app_file = dir_path / "active_app.txt"
    active_app = app_file.read_text().strip() if app_file.exists() else None
    return Frame(
        image=Image.open(BytesIO(image_png)).convert("RGB"),
        image_png=image_png,
        ax=json.loads(ax_json),
        ax_json=ax_json,
        active_app=active_app,
    )


def _macapptree_frame() -> Frame:
    """Capture one real frame in-process: the active window's display + its AX tree.

    The screenshot is taken in memory via Quartz and the AX tree is built in memory via
    macapptree's ``UIElement``, so no plaintext capture ever touches disk (REQ-SEC-001) —
    unlike macapptree's CLI, which shells out to ``screencapture`` / ``python -m
    macapptree.main`` and writes temp files. The frontmost app is captured passively (never
    activated), so recording does not steal focus.

    On multi-monitor setups the display holding the frontmost window is shot — not
    unconditionally the main display — so the screenshot and the AX tree describe the same
    window (REQ-RECORD-010). The window's on-screen bounds come from the very AX element the
    tree was built from, keeping the two in lockstep.
    """
    active_app, pid = _frontmost_app()
    ax, window_bounds = _capture_ax_tree(pid) if pid is not None else ({}, None)
    image_png = _screenshot_png(_active_display_id(window_bounds))
    image = Image.open(BytesIO(image_png)).convert("RGB")
    ax_json = json.dumps(ax, ensure_ascii=False).encode("utf-8")
    return Frame(image=image, image_png=image_png, ax=ax, ax_json=ax_json, active_app=active_app)


def _frontmost_app() -> tuple[str | None, int | None]:
    """The active application's (localized name, pid) via NSWorkspace, or (None, None)."""
    import AppKit  # lazy: pyobjc is only needed on a real capture

    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None, None
    return app.localizedName(), app.processIdentifier()


def _capture_ax_tree(pid: int) -> tuple[dict, Bounds | None]:
    """The frontmost app's main-window AX tree and that window's on-screen bounds.

    Returns ``({}, None)`` if the app exposes no windows. Mirrors macapptree's own ``main``:
    enumerate the app's AX windows and keep the one with the most descendants — but
    in-process, without activating the app or writing a file. The chosen window's bounds are
    returned alongside the tree so the screenshot can target the same window's display
    (REQ-RECORD-010).
    """
    import macapptree.apps as apps  # lazy: heavy pyobjc-backed import
    from macapptree.uielement import UIElement

    app_ref = apps.application_for_process_id(pid)
    windows = apps.windows_for_application(app_ref)
    if not windows:
        return {}, None
    elements = [UIElement(window, max_depth=_AX_MAX_DEPTH) for window in windows]
    main_window = max(elements, key=lambda element: len(element.recursive_children()))
    return main_window.to_dict(), _window_bounds(main_window)


def _window_bounds(element) -> Bounds | None:
    """``(x, y, w, h)`` of an AX window in the global, top-left-origin coordinate space.

    Reads macapptree's ``absolute_position`` (the unadjusted screen origin) and ``size``;
    returns ``None`` if either is missing, in which case display selection defaults to the
    main display. This space matches ``CGDisplayBounds``, so the two compose directly.
    """
    position = getattr(element, "absolute_position", None)
    size = getattr(element, "size", None)
    if position is None or size is None:
        return None
    return (position.x, position.y, size.width, size.height)


# ── active-display selection (REQ-RECORD-010) ───────────────────────────────────


def _active_display_id(window_bounds: Bounds | None) -> int:
    """The ``CGDirectDisplayID`` of the display holding the active window.

    Falls back to the main display when the window's bounds are unknown — the common
    single-monitor case never enumerates displays. The native enumeration is kept behind
    :func:`_online_display_bounds`; the contains-the-center geometry lives in the pure,
    unit-tested :func:`_select_display` (REQ-RECORD-010, ADR-014).
    """
    main_id = _main_display_id()
    if window_bounds is None:
        return main_id
    return _select_display(window_bounds, _online_display_bounds(), fallback_id=main_id)


def _select_display(
    window_bounds: Bounds | None, displays: list[tuple[int, Bounds]], fallback_id: int
) -> int:
    """The id of the display whose rect contains the window's center, else ``fallback_id``.

    Pure geometry over ``displays`` (``[(display_id, (x, y, w, h)), …]``). Falls back when the
    window's bounds are unknown, or when its center lies over no display (straddling a gap)
    rather than guessing. Mirrors how macOS attributes a window to the display holding the
    bulk of it.
    """
    if window_bounds is None:
        return fallback_id
    x, y, w, h = window_bounds
    cx, cy = x + w / 2.0, y + h / 2.0
    for display_id, (dx, dy, dw, dh) in displays:
        if dx <= cx < dx + dw and dy <= cy < dy + dh:
            return display_id
    return fallback_id


def _main_display_id() -> int:
    import Quartz  # lazy

    return Quartz.CGMainDisplayID()


def _cg_online_display_ids() -> list[int]:
    """The ``CGDirectDisplayID``s of all online displays (native)."""
    import Quartz  # lazy

    err, ids, count = Quartz.CGGetOnlineDisplayList(_MAX_DISPLAYS, None, None)
    if err != 0:
        return []
    return list(ids)[:count]


def _online_display_bounds() -> list[tuple[int, Bounds]]:
    """``[(display_id, (x, y, w, h)), …]`` for every online display (native)."""
    import Quartz  # lazy

    result: list[tuple[int, Bounds]] = []
    for display_id in _cg_online_display_ids():
        rect = Quartz.CGDisplayBounds(display_id)
        result.append(
            (display_id, (rect.origin.x, rect.origin.y, rect.size.width, rect.size.height))
        )
    return result


def _screenshot_png(display_id: int | None = None) -> bytes:
    """A PNG of one display (the main display by default), captured in memory (no temp file).

    Returns the encoded PNG bytes; the caller decodes them to the :class:`Frame` image so the
    stored ciphertext and the dedupe image derive from identical bytes. ``display_id`` selects
    the display to shoot — the recorder passes the one holding the active window
    (REQ-RECORD-010).

    The authoritative Screen-Recording gate is the preflight in :func:`ensure_available`
    (``CGPreflightScreenCaptureAccess``), run before the store is even unlocked: without the
    grant ``CGDisplayCreateImage`` returns a *black* image rather than ``None``, so it cannot
    itself detect a missing permission. The ``None`` check here is a defensive secondary guard
    for access revoked between that preflight and this call, surfaced as the same permission
    error the preflight raises.
    """
    import AppKit  # lazy
    import Quartz  # lazy

    if display_id is None:
        display_id = Quartz.CGMainDisplayID()
    cg_image = Quartz.CGDisplayCreateImage(display_id)
    if cg_image is None:
        raise errors.permission_missing(
            "Screen Recording permission not granted; enable norm under "
            "System Settings → Privacy & Security and retry"
        )
    rep = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(cg_image)
    data = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    if data is None:
        raise errors.NormError(
            "CAPTURE_FAILED", errors.ExitCode.RUNTIME_ERROR, "could not encode screenshot as PNG"
        )
    return bytes(data)
