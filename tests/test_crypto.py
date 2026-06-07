"""Unit tests for the crypto layer (below the CLI).

Complements the black-box init tests: the data-key wrapping and AES-256-GCM blob
encryption are security invariants (REQ-INIT-003, REQ-SEC-007, REQ-SEC-001) best
asserted directly rather than only through the CLI.
"""

import base64
import json

import pytest

from norm import crypto


def test_generate_data_key_is_256_bit():
    key = crypto.generate_data_key()
    assert isinstance(key, bytes)
    assert len(key) == 32


def test_wrap_unwrap_roundtrip():
    key = crypto.generate_data_key()
    wrapped = crypto.wrap_data_key(key, "correct horse")
    assert crypto.unwrap_data_key(wrapped, "correct horse") == key


def test_wrong_password_raises_invalid_passphrase():
    wrapped = crypto.wrap_data_key(crypto.generate_data_key(), "right")
    with pytest.raises(crypto.InvalidPassphrase):
        crypto.unwrap_data_key(wrapped, "wrong")


def test_wrapped_blob_uses_argon2id_and_hides_raw_key():
    key = crypto.generate_data_key()
    wrapped = crypto.wrap_data_key(key, "pw")
    assert wrapped["kdf"] == "argon2id"
    for field in ("salt", "nonce", "wrapped_key"):
        assert field in wrapped and wrapped[field]
    blob = json.dumps(wrapped).encode()
    # Neither the raw key bytes nor their base64 may appear in the wrapped file.
    assert key not in blob
    assert base64.b64encode(key) not in blob


def test_each_wrap_uses_fresh_salt_and_nonce():
    key = crypto.generate_data_key()
    w1 = crypto.wrap_data_key(key, "pw")
    w2 = crypto.wrap_data_key(key, "pw")
    assert w1["salt"] != w2["salt"]
    assert w1["nonce"] != w2["nonce"]
    assert w1["wrapped_key"] != w2["wrapped_key"]


def test_aesgcm_roundtrip_and_tamper_detection():
    key = crypto.generate_data_key()
    ciphertext = crypto.aesgcm_encrypt(key, b"plaintext payload")
    assert b"plaintext payload" not in ciphertext
    assert crypto.aesgcm_decrypt(key, ciphertext) == b"plaintext payload"

    tampered = bytearray(ciphertext)
    tampered[-1] ^= 0x01
    with pytest.raises(crypto.DecryptionError):
        crypto.aesgcm_decrypt(key, bytes(tampered))


# ── key hygiene: zero the in-memory data key on shutdown (RECORD-006, SEC) ───────


def test_scrub_zeros_key_buffer_in_place():
    key = bytearray(b"\xa5" * crypto.DATA_KEY_BYTES)
    crypto.scrub(key)
    assert key == bytearray(crypto.DATA_KEY_BYTES)  # all zero...
    assert len(key) == crypto.DATA_KEY_BYTES  # ...same length, mutated in place


def test_scrubbed_key_still_usable_as_an_aesgcm_key_until_scrubbed():
    """The working key is a bytearray so it can be zeroed; it must still encrypt."""
    key = bytearray(crypto.generate_data_key())
    ciphertext = crypto.aesgcm_encrypt(key, b"payload")
    assert crypto.aesgcm_decrypt(key, ciphertext) == b"payload"
    crypto.scrub(key)
    assert key == bytearray(crypto.DATA_KEY_BYTES)
