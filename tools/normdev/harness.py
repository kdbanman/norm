"""The ephemeral-store driver shared by the test suite and the dev ``smoke`` command.

A :class:`NormStore` is "a norm store under throwaway paths, driven through the
real CLI as a subprocess": it owns an isolated ``--config`` file and ``--data-dir``
and runs ``python -m norm`` against them with the passphrase / capture seams wired
in. This is the durable form of the manual ``rm -rf /tmp/normsmoke; init; record …``
pattern — isolation and (for the test fixture) cleanup come for free, and the real
user's store under ``~/.norm`` / ``~/Library/Application Support/norm`` is never
touched.

The pytest ``store`` fixture (``tests/conftest.py``) subclasses this so the tests
and a hand-run smoke exercise the exact same code path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

# The canonical non-interactive passphrase. Tests and smoke runs share it so a
# store created by one is openable the same way by the other.
PASSPHRASE = "correct horse battery staple"

# A minimal AX tree for fabricated captures (one window, one button).
DEFAULT_AX = {
    "role": "AXWindow",
    "title": "Editor",
    "children": [{"role": "AXButton", "title": "OK"}],
}


class NormStore:
    """Drive ``python -m norm`` against an isolated config + data dir under ``base``."""

    def __init__(self, base: str | os.PathLike[str]):
        self.base = Path(base)
        self.config_file = self.base / ".norm" / "config.toml"
        self.data_dir = self.base / "data"

    def run(
        self,
        *argv: str,
        passphrase: str | None = PASSPHRASE,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Invoke ``norm --config <cf> --data-dir <dd> <argv...>`` non-interactively.

        ``passphrase=None`` runs with no ``NORM_PASSPHRASE`` (a locked store);
        stdin is closed so no command can block on a prompt. ``extra_env`` injects
        additional variables (e.g. the hidden ``NORM_FAKE_*`` / ``NORM_FORCE_*``
        capture seams).
        """
        env = {k: v for k, v in os.environ.items() if k != "NORM_PASSPHRASE"}
        if passphrase is not None:
            env["NORM_PASSPHRASE"] = passphrase
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [
                sys.executable, "-m", "norm",
                "--config", str(self.config_file),
                "--data-dir", str(self.data_dir),
                *argv,
            ],
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
        )

    def init(
        self, *extra: str, passphrase: str | None = PASSPHRASE
    ) -> subprocess.CompletedProcess[str]:
        """``norm init --skip-model`` against this store; asserts it succeeded."""
        result = self.run("init", "--skip-model", *extra, passphrase=passphrase)
        assert result.returncode == 0, result.stderr
        return result

    def is_initialized(self) -> bool:
        """True iff the store is provisioned, asked of the product itself.

        Uses ``norm status`` (which never prompts or fails) rather than peeking at
        on-disk files, so the harness stays a pure black-box driver.
        """
        result = self.run("status", "--json")
        if result.returncode != 0:
            return False
        try:
            return bool(json.loads(result.stdout).get("initialized"))
        except (ValueError, AttributeError):
            return False

    def json_out(self, result: subprocess.CompletedProcess[str]):
        """Parse a command's stdout as JSON (for ``--json`` invocations)."""
        return json.loads(result.stdout)


# ── fabricated captures (shared by `smoke` and `run`) ─────────────────────────


def gradient(*, vertical: bool = False, size: int = 64) -> Image.Image:
    """A deterministic grayscale gradient — a stand-in screenshot for the seam."""
    img = Image.new("L", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = (y if vertical else x) * 255 // size
    return img


def write_fake_frame(
    dir_path: str | os.PathLike[str],
    *,
    image: Image.Image | None = None,
    ax: dict | None = None,
    app: str | None = "TextEdit",
) -> str:
    """Materialize an image+AX(+app) capture for the ``NORM_FAKE_CAPTURE`` seam.

    Defaults give a single ready-to-use frame; callers needing distinct frames
    (e.g. dedupe scenarios) pass explicit ``image`` / ``ax`` / ``app``.
    """
    out = Path(dir_path)
    out.mkdir(parents=True, exist_ok=True)
    (image if image is not None else gradient()).save(out / "image.png")
    (out / "ax.json").write_text(json.dumps(ax if ax is not None else DEFAULT_AX))
    if app is not None:
        (out / "active_app.txt").write_text(app)
    return str(out)


def capture_env(frame_dir: str, *, idle: str = "0") -> dict[str, str]:
    """The env that points ``record`` at a fabricated frame instead of the screen."""
    return {"NORM_FAKE_CAPTURE": frame_dir, "NORM_FAKE_IDLE": idle}
