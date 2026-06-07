"""Unit tests for app-password resolution on the *unlock* path.

Order (concept §7): NORM_PASSPHRASE env > chmod-400 file under ~/.norm/ >
interactive prompt. With no source and no TTY (or prompting disabled) it is an
auth failure (STORE_LOCKED, exit 3) rather than a hang.
"""

from __future__ import annotations

import pytest

from norm import errors, passphrase


def test_env_takes_precedence_over_file(tmp_path, monkeypatch):
    (tmp_path / passphrase.PASSPHRASE_FILE).write_text("from-file")
    monkeypatch.setenv(passphrase.ENV_PASSPHRASE, "from-env")
    assert passphrase.acquire_passphrase(tmp_path) == "from-env"


def test_file_used_when_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv(passphrase.ENV_PASSPHRASE, raising=False)
    (tmp_path / passphrase.PASSPHRASE_FILE).write_text("from-file\n")
    # a trailing newline in the file is not part of the password
    assert passphrase.acquire_passphrase(tmp_path) == "from-file"


def test_no_source_without_prompt_raises_store_locked(tmp_path, monkeypatch):
    monkeypatch.delenv(passphrase.ENV_PASSPHRASE, raising=False)
    with pytest.raises(errors.NormError) as ei:
        passphrase.acquire_passphrase(tmp_path, allow_prompt=False)
    assert ei.value.exit_code == errors.ExitCode.AUTH_ERROR
    assert ei.value.code == "STORE_LOCKED"


def test_prompt_used_as_last_resort(tmp_path, monkeypatch):
    monkeypatch.delenv(passphrase.ENV_PASSPHRASE, raising=False)
    monkeypatch.setattr(passphrase.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(passphrase.getpass, "getpass", lambda prompt="": "typed")
    assert passphrase.acquire_passphrase(tmp_path) == "typed"
