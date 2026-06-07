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

# The canonical non-interactive passphrase. Tests and smoke runs share it so a
# store created by one is openable the same way by the other.
PASSPHRASE = "correct horse battery staple"


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

    def json_out(self, result: subprocess.CompletedProcess[str]):
        """Parse a command's stdout as JSON (for ``--json`` invocations)."""
        return json.loads(result.stdout)
