"""Shared fixtures for the black-box CLI tests.

Each test gets a :class:`CliStore` bound to an isolated tmp config file + data
dir, so a test can ``init`` a store and then run further commands against it the
same way a user would: ``python -m norm`` as a subprocess, asserting on
stdout/stderr/exit code (never on internal state).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PASSPHRASE = "correct horse battery staple"


class CliStore:
    """A norm store under tmp paths, driven through the real CLI."""

    def __init__(self, tmp_path: Path):
        self.config_file = tmp_path / ".norm" / "config.toml"
        self.data_dir = tmp_path / "data"

    def run(self, *argv: str, passphrase: str | None = PASSPHRASE) -> subprocess.CompletedProcess[str]:
        """Invoke ``norm --config <cf> --data-dir <dd> <argv...>`` non-interactively.

        ``passphrase=None`` runs with no ``NORM_PASSPHRASE`` (a locked store);
        stdin is closed so no command can block on a prompt.
        """
        env = {k: v for k, v in os.environ.items() if k != "NORM_PASSPHRASE"}
        if passphrase is not None:
            env["NORM_PASSPHRASE"] = passphrase
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

    def init(self, *extra: str, passphrase: str | None = PASSPHRASE) -> subprocess.CompletedProcess[str]:
        result = self.run("init", "--skip-model", *extra, passphrase=passphrase)
        assert result.returncode == 0, result.stderr
        return result

    def json_out(self, result: subprocess.CompletedProcess[str]):
        return json.loads(result.stdout)


@pytest.fixture
def store(tmp_path) -> CliStore:
    return CliStore(tmp_path)
