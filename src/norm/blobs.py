"""Encrypted blob files: the image and AX payloads referenced by capture rows.

Each capture's screenshot and AX JSON are stored as separate AES-256-GCM blobs under
``data_dir/blobs/`` (concept §7); the index row holds only an opaque ``*_ref`` name.
Blobs are written ciphertext-only — no plaintext capture is ever placed on disk
(REQ-SEC-001) — and decrypted transiently in memory by readers (show/export, and the
report pipeline) (REQ-SEC-006).

Blob names are random tokens, not capture ids: a row is the single source of truth
for what a blob is, so a blob can be written before its row exists without leaking
ordering or count, and an interrupted write leaves at most a harmless orphan file.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from norm import crypto, fsutil


def write_blob(blobs_dir: Path, data_key: bytes, plaintext: bytes) -> str:
    """Encrypt ``plaintext`` to a fresh blob file and return its reference name."""
    blobs_dir = Path(blobs_dir)
    blobs_dir.mkdir(parents=True, exist_ok=True)
    ref = secrets.token_hex(16) + ".blob"
    fsutil.atomic_write(blobs_dir / ref, crypto.aesgcm_encrypt(data_key, plaintext))
    return ref


def read_blob(blobs_dir: Path, data_key: bytes, ref: str) -> bytes:
    """Decrypt and return the plaintext of blob ``ref`` under ``blobs_dir``."""
    return crypto.aesgcm_decrypt(data_key, (Path(blobs_dir) / ref).read_bytes())


def delete_blob(blobs_dir: Path, ref: str) -> None:
    """Best-effort remove blob ``ref``; a missing file is not an error.

    Used by ``prune`` (capture image/AX + report markdown blobs) and the ``--force``
    preprocess overwrite (dropping a stale markdown blob). A blob ref belongs to a
    single row, so deleting it never affects another (concept §7).
    """
    try:
        (Path(blobs_dir) / ref).unlink()
    except OSError:
        pass
