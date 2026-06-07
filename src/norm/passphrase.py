"""Resolving the app password.

Sources, in order (concept §7): the ``NORM_PASSPHRASE`` environment variable, then
an interactive no-echo prompt. The chmod-400 password file used for unattended
daemon unlock is read by the record daemon, not at init time.

Interactive prompts are skipped when there is no TTY; a non-interactive run with no
``NORM_PASSPHRASE`` is an auth failure rather than a hang (REQ-INIT-003).
"""

from __future__ import annotations

import getpass
import os
import sys

from norm import errors

ENV_PASSPHRASE = "NORM_PASSPHRASE"


def _from_env() -> str | None:
    value = os.environ.get(ENV_PASSPHRASE)
    return value if value else None


def acquire_new_passphrase() -> str:
    """Get the app password when *creating* the store (init).

    Uses ``NORM_PASSPHRASE`` if set; otherwise prompts twice and requires a match.
    Raises a STORE_LOCKED :class:`~norm.errors.NormError` if no password can be
    obtained without a TTY.
    """
    env = _from_env()
    if env is not None:
        return env

    if not sys.stdin.isatty():
        raise errors.store_locked(
            "no app password provided; set NORM_PASSPHRASE or run init in a terminal"
        )

    first = getpass.getpass("Set app password: ")
    if not first:
        raise errors.store_locked("app password must not be empty")
    second = getpass.getpass("Confirm app password: ")
    if first != second:
        raise errors.store_locked("passwords did not match")
    return first
