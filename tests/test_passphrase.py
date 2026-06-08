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


# ── rotation resolution: old (verify) + new (set), REQ-SEC-005 ────────────────


def _clear_pw_env(monkeypatch):
    for var in (
        passphrase.ENV_PASSPHRASE,
        passphrase.ENV_OLD_PASSPHRASE,
        passphrase.ENV_NEW_PASSPHRASE,
    ):
        monkeypatch.delenv(var, raising=False)


def test_old_passphrase_from_env(monkeypatch):
    _clear_pw_env(monkeypatch)
    monkeypatch.setenv(passphrase.ENV_OLD_PASSPHRASE, "current")
    assert passphrase.acquire_old_passphrase() == "current"


def test_old_passphrase_does_not_fall_back_to_unlock_sources(tmp_path, monkeypatch):
    # The current password must be supplied for rotation specifically; an unlocked
    # daemon's NORM_PASSPHRASE / passphrase file must NOT authorize a rotation.
    _clear_pw_env(monkeypatch)
    monkeypatch.setenv(passphrase.ENV_PASSPHRASE, "unlock-secret")
    (tmp_path / passphrase.PASSPHRASE_FILE).write_text("file-secret")
    monkeypatch.setattr(passphrase.sys.stdin, "isatty", lambda: False)
    with pytest.raises(errors.NormError) as ei:
        passphrase.acquire_old_passphrase()
    assert ei.value.code == "STORE_LOCKED"


def test_old_passphrase_prompt_when_no_env(monkeypatch):
    _clear_pw_env(monkeypatch)
    monkeypatch.setattr(passphrase.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(passphrase.getpass, "getpass", lambda prompt="": "typed-old")
    assert passphrase.acquire_old_passphrase() == "typed-old"


def test_new_passphrase_from_dedicated_env(monkeypatch):
    _clear_pw_env(monkeypatch)
    # NORM_NEW_PASSPHRASE is read; the init-path NORM_PASSPHRASE is ignored here.
    monkeypatch.setenv(passphrase.ENV_PASSPHRASE, "init-secret")
    monkeypatch.setenv(passphrase.ENV_NEW_PASSPHRASE, "replacement")
    assert (
        passphrase.acquire_new_passphrase(env_var=passphrase.ENV_NEW_PASSPHRASE)
        == "replacement"
    )


def test_new_passphrase_missing_non_interactive_raises(monkeypatch):
    _clear_pw_env(monkeypatch)
    monkeypatch.setattr(passphrase.sys.stdin, "isatty", lambda: False)
    with pytest.raises(errors.NormError) as ei:
        passphrase.acquire_new_passphrase(env_var=passphrase.ENV_NEW_PASSPHRASE)
    assert ei.value.code == "STORE_LOCKED"
