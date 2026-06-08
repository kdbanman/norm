"""Resolving the app password.

Two paths, both honouring the concept §7 sources:

* *Creating* a store (init) — :func:`acquire_new_passphrase`: ``NORM_PASSPHRASE``
  or a confirmed interactive prompt.
* *Unlocking* an existing store — :func:`acquire_passphrase`: ``NORM_PASSPHRASE``
  env > a chmod-400 file under ``~/.norm/`` (unattended/daemon unlock) > a single
  interactive no-echo prompt.
* *Rotating* the password (passwd) — :func:`acquire_old_passphrase` proves the
  current password (``NORM_OLD_PASSPHRASE`` or a no-echo prompt; no file fallback),
  and :func:`acquire_new_passphrase` is reused with ``NORM_NEW_PASSPHRASE`` to set
  the replacement (REQ-SEC-005).

Interactive prompts are skipped when there is no TTY; a non-interactive run with no
password source is an auth failure (STORE_LOCKED, exit 3) rather than a hang
(REQ-INIT-003, REQ-SEC-004).
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from norm import errors

ENV_PASSPHRASE = "NORM_PASSPHRASE"
# Rotation seams (REQ-SEC-005): the only non-interactive path for `passwd`.
ENV_OLD_PASSPHRASE = "NORM_OLD_PASSPHRASE"
ENV_NEW_PASSPHRASE = "NORM_NEW_PASSPHRASE"
# Headless unlock source: a chmod-400 file under ~/.norm/ (REQ-SEC-007). Read by
# the record daemon and any non-interactive unlock; never written by norm itself.
PASSPHRASE_FILE = "passphrase"


def _from_env(name: str = ENV_PASSPHRASE) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def _from_file(config_dir: Path) -> str | None:
    path = Path(config_dir) / PASSPHRASE_FILE
    if not path.exists():
        return None
    # A single trailing newline is editor noise, not part of the password.
    value = path.read_text().rstrip("\n")
    return value or None


def acquire_passphrase(config_dir: Path, *, allow_prompt: bool = True) -> str:
    """Resolve the app password for *unlocking* an existing store.

    Order: ``NORM_PASSPHRASE`` > chmod-400 file under ``config_dir`` > interactive
    prompt (only when ``allow_prompt`` and a TTY is present). Raises a STORE_LOCKED
    :class:`~norm.errors.NormError` when no source yields a password — callers that
    must never fail (``status``) pass ``allow_prompt=False`` and catch it.
    """
    env = _from_env()
    if env is not None:
        return env

    from_file = _from_file(config_dir)
    if from_file is not None:
        return from_file

    if allow_prompt and sys.stdin.isatty():
        typed = getpass.getpass("App password: ")
        if typed:
            return typed

    raise errors.store_locked(
        "store locked: no app password available "
        "(set NORM_PASSPHRASE, add a ~/.norm passphrase file, or run in a terminal)"
    )


def acquire_new_passphrase(
    *,
    env_var: str = ENV_PASSPHRASE,
    set_prompt: str = "Set app password: ",
    confirm_prompt: str = "Confirm app password: ",
    no_source_hint: str = "set NORM_PASSPHRASE or run init in a terminal",
) -> str:
    """Get the app password being *set* — by init (the data key's first wrapping) or
    by passwd (its new wrapping, ``env_var=NORM_NEW_PASSPHRASE``).

    Uses ``env_var`` if set; otherwise prompts twice and requires a match. Raises a
    STORE_LOCKED :class:`~norm.errors.NormError` if no password can be obtained
    without a TTY.
    """
    env = _from_env(env_var)
    if env is not None:
        return env

    if not sys.stdin.isatty():
        raise errors.store_locked(f"no app password provided; {no_source_hint}")

    first = getpass.getpass(set_prompt)
    if not first:
        raise errors.store_locked("app password must not be empty")
    second = getpass.getpass(confirm_prompt)
    if first != second:
        raise errors.store_locked("passwords did not match")
    return first


def acquire_old_passphrase() -> str:
    """Resolve the *current* app password for rotation (passwd).

    ``NORM_OLD_PASSPHRASE`` env, else a single no-echo prompt. Deliberately offers
    no chmod-400-file or ``NORM_PASSPHRASE`` fallback: rotation must be authorized by
    someone who can supply the current password, not merely by an unlocked daemon
    (REQ-SEC-005). The command still *verifies* it by unwrapping the data key.
    """
    env = _from_env(ENV_OLD_PASSPHRASE)
    if env is not None:
        return env

    if sys.stdin.isatty():
        typed = getpass.getpass("Current app password: ")
        if typed:
            return typed

    raise errors.store_locked(
        "store locked: no current app password available "
        "(set NORM_OLD_PASSPHRASE or run in a terminal)"
    )
