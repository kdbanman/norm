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
    """Capture one real frame in-process: the active display + the frontmost app's AX tree.

    The screenshot is taken in memory via Quartz and the AX tree is built in memory via
    macapptree's ``UIElement``, so no plaintext capture ever touches disk (REQ-SEC-001) —
    unlike macapptree's CLI, which shells out to ``screencapture`` / ``python -m
    macapptree.main`` and writes temp files. The frontmost app is captured passively (never
    activated), so recording does not steal focus.
    """
    active_app, pid = _frontmost_app()
    ax = _capture_ax_tree(pid) if pid is not None else {}
    image_png = _screenshot_png()
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


def _capture_ax_tree(pid: int) -> dict:
    """The frontmost app's main-window AX tree as a plain dict (empty if it exposes none).

    Mirrors macapptree's own ``main``: enumerate the app's AX windows and keep the one with
    the most descendants — but in-process, without activating the app or writing a file.
    """
    import macapptree.apps as apps  # lazy: heavy pyobjc-backed import
    from macapptree.uielement import UIElement

    app_ref = apps.application_for_process_id(pid)
    windows = apps.windows_for_application(app_ref)
    if not windows:
        return {}
    elements = [UIElement(window, max_depth=_AX_MAX_DEPTH) for window in windows]
    main_window = max(elements, key=lambda element: len(element.recursive_children()))
    return main_window.to_dict()


def _screenshot_png() -> bytes:
    """A PNG of the main display, captured in memory (no temp file).

    Returns the encoded PNG bytes; the caller decodes them to the :class:`Frame` image so the
    stored ciphertext and the dedupe image derive from identical bytes. Active-display
    selection on multi-monitor setups is deferred (REQ-RECORD-010, ADR-014): the main display
    is always captured.

    The authoritative Screen-Recording gate is the preflight in :func:`ensure_available`
    (``CGPreflightScreenCaptureAccess``), run before the store is even unlocked: without the
    grant ``CGDisplayCreateImage`` returns a *black* image rather than ``None``, so it cannot
    itself detect a missing permission. The ``None`` check here is a defensive secondary guard
    for access revoked between that preflight and this call, surfaced as the same permission
    error the preflight raises.
    """
    import AppKit  # lazy
    import Quartz  # lazy

    cg_image = Quartz.CGDisplayCreateImage(Quartz.CGMainDisplayID())
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
