"""Key custody and at-rest encryption primitives.

norm's data is gated on a norm-specific *app password* (concept §7), independent of
the macOS login password and the Keychain. A random 256-bit *data key* encrypts all
blobs and the index; that key is itself Argon2id-wrapped by the app password and
stored on disk (``data_dir/key.json``) — like an encrypted SSH/SSL private key.

This module owns three things and nothing higher-level:

* minting the data key (:func:`generate_data_key`),
* wrapping / unwrapping it with the app password (:func:`wrap_data_key`,
  :func:`unwrap_data_key`),
* AES-256-GCM blob encryption used by the store and (later) capture writers
  (:func:`aesgcm_encrypt`, :func:`aesgcm_decrypt`).
"""

from __future__ import annotations

import base64
import os

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DATA_KEY_BYTES = 32  # AES-256
_SALT_BYTES = 16
_NONCE_BYTES = 12  # GCM standard nonce length

# Argon2id work factors for wrapping the data key. Interactive-grade: the wrap is
# touched once per command, so these favour resistance over speed.
_ARGON2_TIME_COST = 3
_ARGON2_MEMORY_COST = 64 * 1024  # KiB == 64 MiB
_ARGON2_PARALLELISM = 4

WRAP_VERSION = 1


class DecryptionError(Exception):
    """AES-GCM authentication failed (wrong key or tampered ciphertext)."""


class InvalidPassphrase(DecryptionError):
    """The supplied app password did not unwrap the data key."""


def generate_data_key() -> bytes:
    """Mint a fresh random 256-bit data key."""
    return os.urandom(DATA_KEY_BYTES)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text)


def _derive_kek(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit key-encryption key from the app password via Argon2id."""
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=_ARGON2_TIME_COST,
        memory_cost=_ARGON2_MEMORY_COST,
        parallelism=_ARGON2_PARALLELISM,
        hash_len=DATA_KEY_BYTES,
        type=Type.ID,
    )


def aesgcm_encrypt(key: bytes, plaintext: bytes, aad: bytes | None = None) -> bytes:
    """Encrypt ``plaintext`` with AES-256-GCM, returning ``nonce || ciphertext``."""
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return nonce + ciphertext


def aesgcm_decrypt(key: bytes, blob: bytes, aad: bytes | None = None) -> bytes:
    """Decrypt a ``nonce || ciphertext`` blob; raise :class:`DecryptionError` on failure."""
    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise DecryptionError("AES-GCM authentication failed") from exc


def wrap_data_key(data_key: bytes, password: str) -> dict:
    """Argon2id-wrap ``data_key`` with the app password.

    Returns a JSON-serializable dict (the contents of ``key.json``). A fresh salt
    and nonce are drawn per call, so re-wrapping the same key yields a different
    record.
    """
    salt = os.urandom(_SALT_BYTES)
    kek = _derive_kek(password, salt)
    nonce = os.urandom(_NONCE_BYTES)
    wrapped = AESGCM(kek).encrypt(nonce, data_key, None)
    return {
        "version": WRAP_VERSION,
        "kdf": "argon2id",
        "time_cost": _ARGON2_TIME_COST,
        "memory_cost": _ARGON2_MEMORY_COST,
        "parallelism": _ARGON2_PARALLELISM,
        "salt": _b64(salt),
        "nonce": _b64(nonce),
        "wrapped_key": _b64(wrapped),
    }


def unwrap_data_key(wrapped: dict, password: str) -> bytes:
    """Recover the data key from a ``key.json`` record.

    Raises :class:`InvalidPassphrase` if the password is wrong (or the record was
    tampered with).
    """
    kek = hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=_unb64(wrapped["salt"]),
        time_cost=wrapped["time_cost"],
        memory_cost=wrapped["memory_cost"],
        parallelism=wrapped["parallelism"],
        hash_len=DATA_KEY_BYTES,
        type=Type.ID,
    )
    try:
        return AESGCM(kek).decrypt(_unb64(wrapped["nonce"]), _unb64(wrapped["wrapped_key"]), None)
    except InvalidTag as exc:
        raise InvalidPassphrase("incorrect app password") from exc
