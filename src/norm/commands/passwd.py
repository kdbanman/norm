"""``norm passwd`` — rotate the app password by re-wrapping the data key.

The data key never changes; only its Argon2id wrapping does (concept §10.18,
REQ-SEC-005). So rotation is cheap and the on-disk blobs/index are *not* re-encrypted:
we unwrap the data key with the current password (which proves the caller knows it),
re-wrap it under the new password, and atomically swap ``key.json``.

The unwrapped data key is held only as a ``bytearray`` and scrubbed before return, and
nothing plaintext (neither the key nor either password) is ever written to disk —
``atomic_write`` lays down only the new *wrapped* record (REQ-SEC-001/005/006).
"""

from __future__ import annotations

import argparse
import json

from norm import crypto, errors, fsutil, passphrase, session


def configure(parser: argparse.ArgumentParser) -> None:
    """Attach passwd's handler to its subparser (no flags; env/prompt driven)."""
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    paths = session.resolve_paths(args)
    if not session.is_initialized(paths):
        raise errors.not_initialized("store not initialized; run `norm init`")

    # Verify the current password by actually unwrapping the data key (a check that
    # can't be faked). NOT_INITIALIZED above already took precedence over this.
    old = passphrase.acquire_old_passphrase()
    wrapped = json.loads(paths.key_file.read_text())
    try:
        data_key = bytearray(crypto.unwrap_data_key(wrapped, old))
    except crypto.InvalidPassphrase as exc:
        raise errors.store_locked("store locked: incorrect app password") from exc

    try:
        # Acquire the replacement only after the old one verified, so a wrong
        # current password fails before we ever prompt for / read the new one.
        new = passphrase.acquire_new_passphrase(
            env_var=passphrase.ENV_NEW_PASSPHRASE,
            set_prompt="New app password: ",
            confirm_prompt="Confirm new app password: ",
            no_source_hint="set NORM_NEW_PASSPHRASE or run passwd in a terminal",
        )
        rewrapped = crypto.wrap_data_key(data_key, new)
        # Atomic swap: a crash mid-write can't corrupt the sole copy of the wrapped
        # key, and the bytes are owner-only from creation (never a plaintext key).
        fsutil.atomic_write(paths.key_file, json.dumps(rewrapped).encode(), mode=0o600)
    finally:
        crypto.scrub(data_key)

    print("passphrase updated")
    return int(errors.ExitCode.SUCCESS)
