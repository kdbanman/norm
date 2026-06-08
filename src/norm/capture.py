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

The real macapptree binding (:func:`_macapptree_frame`) is finalized alongside the
record loop in a later iteration, mirroring how ``init`` deferred the model download;
until then the seam-driven path is the exercised one.
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
    # The real macapptree binding lands with the record loop (see module docstring).
    raise errors.NormError(
        "MACAPPTREE_BINDING_PENDING",
        errors.ExitCode.RUNTIME_ERROR,
        "real macapptree capture is not wired yet; this iteration is seam-tested",
    )
