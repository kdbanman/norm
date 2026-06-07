"""``norm init`` — create the encrypted store, config, and wrapped data key.

Creates ``~/.norm/`` (mode 0700) with ``config.toml``, the ``data_dir`` holding an
empty encrypted index, and ``key.json`` — a fresh 256-bit data key Argon2id-wrapped
by the app password (REQ-INIT-001/003, REQ-SEC-007). Refuses to clobber an existing
store without ``--force`` (REQ-INIT-002). No macOS Keychain is touched.

Model provisioning (downloading the MLX weights, REQ-INIT-004) is wired in a later
iteration; ``--skip-model`` is accepted and is currently the only behaviour.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from norm import config as config_mod
from norm import crypto, errors, passphrase
from norm import store as store_mod

KEY_FILE = "key.json"
INDEX_FILE = "index.db"
BLOBS_DIR = "blobs"


def configure(parser: argparse.ArgumentParser) -> None:
    """Attach init's flags and handler to its subparser."""
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-initialize even if a store already exists (destroys existing data).",
    )
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="Create the store without downloading the model weights.",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    config_file = config_mod.resolve_config_file(args.config)
    config_dir = config_file.parent
    data_dir = config_mod.resolve_data_dir(args.data_dir)

    key_path = data_dir / KEY_FILE
    index_path = data_dir / INDEX_FILE

    # REQ-INIT-002: refuse to clobber an existing store unless --force. (Usage error
    # takes precedence over a missing password, per the failure-precedence order.)
    if (index_path.exists() or key_path.exists()) and not args.force:
        raise errors.usage_error("store already initialized; use --force to re-initialize")

    # REQ-INIT-003: an app password is always required — acquire it before writing
    # anything, so a failed acquisition leaves the disk untouched.
    password = passphrase.acquire_new_passphrase()

    config_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(config_dir, 0o700)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(data_dir, 0o700)
    (data_dir / BLOBS_DIR).mkdir(exist_ok=True)

    # Mint and wrap the data key, then build the encrypted index with it.
    data_key = crypto.generate_data_key()
    _write_wrapped_key(key_path, crypto.wrap_data_key(data_key, password))
    store_mod.create_index(index_path, data_key)

    config_mod.write_config(config_file, config_mod.default_config(data_dir))
    os.chmod(config_file, 0o600)

    if not args.skip_model:
        # Weight download lands with REQ-INIT-004; until then init always behaves as
        # --skip-model and says so on stderr rather than silently doing nothing.
        print(
            "note: model weights are not downloaded yet; re-run after provisioning",
            file=sys.stderr,
        )

    print(f"initialized norm store\n  config:   {config_file}\n  data dir: {data_dir}")
    return int(errors.ExitCode.SUCCESS)


def _write_wrapped_key(key_path: Path, wrapped: dict) -> None:
    """Write the wrapped data key as owner-only JSON (REQ-SEC-007)."""
    # Create with restrictive mode from the start so the wrapped key is never briefly
    # world-readable.
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(wrapped, fh)
    os.chmod(key_path, 0o600)
