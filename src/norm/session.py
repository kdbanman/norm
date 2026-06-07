"""Store access: locating, detecting, and unlocking the on-disk store.

The shared gateway every data command goes through. It owns the store layout
(:data:`KEY_FILE`, :data:`INDEX_FILE`, :data:`BLOBS_DIR`) and the access contract:

* a never-initialized store → ``NOT_INITIALIZED`` (exit 5);
* a present-but-unlockable store → ``STORE_LOCKED`` (exit 3);

distinct codes, in that precedence (REQ-GLOBAL-007, conventions.exit_precedence).
The unwrapped data key lives only for the life of the command (concept §7).

``open_store`` raises for commands that require data (list, record, report, …).
``status`` instead probes :func:`is_initialized` and a non-prompting
``open_store(allow_prompt=False)`` so it can report locked/unlocked without ever
failing (REQ-DATA-001).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from norm import config as config_mod
from norm import crypto, errors, passphrase
from norm import store as store_mod

# On-disk store layout, relative to data_dir.
KEY_FILE = "key.json"
INDEX_FILE = "index.db"
BLOBS_DIR = "blobs"


@dataclass(frozen=True)
class StorePaths:
    config_file: Path
    config_dir: Path
    data_dir: Path
    key_file: Path
    index_file: Path


def resolve_paths(args: argparse.Namespace) -> StorePaths:
    """Resolve config + data-dir paths from the global flags and config file.

    ``data_dir`` follows precedence ``--data-dir`` > config value > default; the
    config file is consulted only if it exists (an uninitialized machine has none).
    """
    config_file = config_mod.resolve_config_file(getattr(args, "config", None))
    cfg: dict = {}
    if config_file.exists():
        try:
            cfg = config_mod.read_config(config_file)
        except (OSError, ValueError):
            cfg = {}
    data_dir = config_mod.resolve_data_dir(getattr(args, "data_dir", None), cfg)
    return StorePaths(
        config_file=config_file,
        config_dir=config_file.parent,
        data_dir=data_dir,
        key_file=data_dir / KEY_FILE,
        index_file=data_dir / INDEX_FILE,
    )


def is_initialized(paths: StorePaths) -> bool:
    """True iff a store exists: both the wrapped key and the encrypted index."""
    return paths.key_file.exists() and paths.index_file.exists()


def unlock_data_key(paths: StorePaths, *, allow_prompt: bool = True) -> bytes:
    """Acquire the app password and unwrap the data key.

    Raises STORE_LOCKED on a missing password or a wrong one. The caller must have
    already confirmed :func:`is_initialized`.
    """
    password = passphrase.acquire_passphrase(paths.config_dir, allow_prompt=allow_prompt)
    wrapped = json.loads(paths.key_file.read_text())
    try:
        return crypto.unwrap_data_key(wrapped, password)
    except crypto.InvalidPassphrase as exc:
        raise errors.store_locked("store locked: incorrect app password") from exc


def open_store(
    paths: StorePaths, *, allow_prompt: bool = True
) -> tuple[sqlite3.Connection, bytes]:
    """Open the store for a data command: returns ``(index connection, data key)``.

    Raises ``NOT_INITIALIZED`` (exit 5) before ``STORE_LOCKED`` (exit 3), matching
    the failure precedence. The connection is in-memory; the caller closes it and,
    for writers, flushes via :mod:`norm.store`.
    """
    if not is_initialized(paths):
        raise errors.not_initialized("store not initialized; run `norm init`")
    data_key = unlock_data_key(paths, allow_prompt=allow_prompt)
    try:
        con = store_mod.open_index(paths.index_file, data_key)
    except crypto.DecryptionError as exc:
        # Key unwrapped but the index won't authenticate: treat as locked/tampered.
        raise errors.store_locked("store locked: index could not be decrypted") from exc
    return con, data_key
