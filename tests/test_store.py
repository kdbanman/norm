"""Unit tests for the encrypted index (below the CLI).

The index is an in-memory SQLite database serialized and AES-256-GCM-encrypted at
rest (data_dir/index.db). These tests assert the schema, the ciphertext-at-rest
property (REQ-SEC-001), and that the wrong key cannot open it.
"""

import pytest

from norm import crypto, store

EXPECTED_TABLES = {"capture", "preprocess", "interval_report"}


def _tables(con):
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in rows}


def test_create_index_writes_full_schema(tmp_path):
    key = crypto.generate_data_key()
    index = tmp_path / "index.db"
    store.create_index(index, key)
    assert index.exists()
    con = store.open_index(index, key)
    assert EXPECTED_TABLES <= _tables(con)


def test_index_file_is_ciphertext_not_sqlite(tmp_path):
    key = crypto.generate_data_key()
    index = tmp_path / "index.db"
    store.create_index(index, key)
    raw = index.read_bytes()
    assert raw[:16] != b"SQLite format 3\x00"


def test_wrong_key_cannot_open(tmp_path):
    key = crypto.generate_data_key()
    index = tmp_path / "index.db"
    store.create_index(index, key)
    with pytest.raises(crypto.DecryptionError):
        store.open_index(index, crypto.generate_data_key())


def test_flush_persists_changes(tmp_path):
    key = crypto.generate_data_key()
    index = tmp_path / "index.db"
    store.create_index(index, key)

    con = store.open_index(index, key)
    con.execute(
        "INSERT INTO capture "
        "(ts, active_app, idle_gap_s, phash, ax_hash, image_ref, ax_ref, duration_s) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-01-01T00:00:00", "App", 0, "ph", "ax", "img", "axref", 60),
    )
    store.flush_index(con, index, key)

    reopened = store.open_index(index, key)
    assert reopened.execute("SELECT COUNT(*) FROM capture").fetchone()[0] == 1
