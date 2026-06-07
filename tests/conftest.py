"""Shared fixtures for the black-box CLI tests.

Each test gets a :class:`CliStore` bound to an isolated tmp config file + data
dir, so a test can ``init`` a store and then run further commands against it the
same way a user would: ``python -m norm`` as a subprocess, asserting on
stdout/stderr/exit code (never on internal state).

The driver itself lives in :mod:`tools.normdev.harness` so the tests and the
dev ``smoke`` command (``python -m tools.normdev smoke``) exercise the exact
same ephemeral-store code path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.normdev.harness import PASSPHRASE, NormStore  # noqa: F401  (re-exported)


class CliStore(NormStore):
    """A norm store under tmp paths, driven through the real CLI."""

    def __init__(self, tmp_path: Path):
        super().__init__(tmp_path)


@pytest.fixture
def store(tmp_path) -> CliStore:
    return CliStore(tmp_path)
