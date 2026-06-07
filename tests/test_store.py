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


# ── count + range-query helpers (REQ-DATA-001 / REQ-DATA-002) ──────────────────


def _add_capture(con, ts, app="App"):
    con.execute(
        "INSERT INTO capture "
        "(ts, active_app, idle_gap_s, phash, ax_hash, image_ref, ax_ref, duration_s) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, app, 0, "ph", "ax", "img", "axref", 60),
    )


def _open(tmp_path):
    key = crypto.generate_data_key()
    index = tmp_path / "index.db"
    store.create_index(index, key)
    return store.open_index(index, key)


def test_counts_zero_on_fresh_index(tmp_path):
    con = _open(tmp_path)
    c = store.counts(con)
    assert c == {
        "captures": 0,
        "last_capture": None,
        "preprocess": 0,
        "interval_reports": 0,
    }


def test_counts_reflect_rows(tmp_path):
    con = _open(tmp_path)
    _add_capture(con, "2026-06-06T10:00:00")
    _add_capture(con, "2026-06-06T12:00:00")
    c = store.counts(con)
    assert c["captures"] == 2
    assert c["last_capture"] == "2026-06-06T12:00:00"


def test_list_captures_returns_metadata_fields_ordered(tmp_path):
    con = _open(tmp_path)
    _add_capture(con, "2026-06-06T12:00:00", app="B")
    _add_capture(con, "2026-06-06T10:00:00", app="A")
    rows = store.list_captures(con)
    assert [r["active_app"] for r in rows] == ["A", "B"]  # ordered by ts
    assert set(rows[0]) == {"id", "ts", "active_app", "idle_gap_s", "duration_s"}


def test_list_captures_filters_by_range_half_open(tmp_path):
    con = _open(tmp_path)
    _add_capture(con, "2026-06-06T09:00:00")
    _add_capture(con, "2026-06-06T11:00:00")
    _add_capture(con, "2026-06-06T13:00:00")
    rows = store.list_captures(con, start="2026-06-06T11:00:00", end="2026-06-06T13:00:00")
    # start inclusive, end exclusive
    assert [r["ts"] for r in rows] == ["2026-06-06T11:00:00"]
