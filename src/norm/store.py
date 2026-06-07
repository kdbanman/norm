"""The encrypted index.

The index is an ordinary SQLite database that lives **only in memory** while a
command runs. At rest it is serialized (:meth:`sqlite3.Connection.serialize`) and
AES-256-GCM-encrypted with the data key into ``data_dir/index.db`` — so the on-disk
file carries no ``SQLite format 3\\0`` header and is unreadable without the key
(REQ-SEC-001). A norm command opens the index, mutates it in memory, and
:func:`flush_index` writes the ciphertext back; no plaintext database is ever
written to disk.

The original spec named SQLCipher; SQLCipher has no installable build for
arm64/CPython 3.12, so the index is encrypted at the file level instead. See the
decision record and concept §7 for the rationale; the security contract is
unchanged.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from norm import crypto

SCHEMA_VERSION = 1

# Mirrors the data model in concept §6. capture_ids / source_preprocess_ids hold
# JSON arrays of ids; timestamps are ISO-8601 text.
_SCHEMA = """
CREATE TABLE capture (
    id          INTEGER PRIMARY KEY,
    ts          TEXT    NOT NULL,
    active_app  TEXT,
    idle_gap_s  INTEGER NOT NULL DEFAULT 0,
    phash       TEXT    NOT NULL,
    ax_hash     TEXT    NOT NULL,
    image_ref   TEXT    NOT NULL,
    ax_ref      TEXT    NOT NULL,
    duration_s  INTEGER NOT NULL
);

CREATE TABLE preprocess (
    id            INTEGER PRIMARY KEY,
    window_start  TEXT    NOT NULL,
    window_end    TEXT    NOT NULL,
    capture_ids   TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    prompt_id     TEXT    NOT NULL,
    prompt_text   TEXT    NOT NULL,
    markdown_ref  TEXT    NOT NULL
);

CREATE TABLE interval_report (
    id                     INTEGER PRIMARY KEY,
    generated_at           TEXT    NOT NULL,
    range_from             TEXT    NOT NULL,
    range_to               TEXT    NOT NULL,
    model                  TEXT    NOT NULL,
    prompt_id              TEXT    NOT NULL,
    prompt_text            TEXT    NOT NULL,
    source_preprocess_ids  TEXT    NOT NULL,
    markdown_ref           TEXT    NOT NULL
);

CREATE TABLE meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def _new_memory_db() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def open_index(path: Path, data_key: bytes) -> sqlite3.Connection:
    """Decrypt ``path`` and return an in-memory connection to the index.

    Raises :class:`crypto.DecryptionError` if ``data_key`` is wrong or the file was
    tampered with.
    """
    blob = crypto.aesgcm_decrypt(data_key, Path(path).read_bytes())
    con = _new_memory_db()
    con.deserialize(blob)
    return con


def flush_index(con: sqlite3.Connection, path: Path, data_key: bytes) -> None:
    """Serialize ``con``, encrypt it with ``data_key``, and atomically write ``path``."""
    con.commit()
    ciphertext = crypto.aesgcm_encrypt(data_key, con.serialize())
    _atomic_write(Path(path), ciphertext)


def create_index(path: Path, data_key: bytes) -> None:
    """Build a fresh, empty index with the full schema and write it encrypted."""
    con = _new_memory_db()
    try:
        con.executescript(_SCHEMA)
        con.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        flush_index(con, path, data_key)
    finally:
        con.close()


def counts(con: sqlite3.Connection) -> dict:
    """Summary counters for ``status`` (REQ-DATA-001), read from the index alone.

    No blob is decrypted: every figure comes from index metadata.
    """
    captures, last_capture = con.execute(
        "SELECT COUNT(*), MAX(ts) FROM capture"
    ).fetchone()
    return {
        "captures": captures,
        "last_capture": last_capture,
        "preprocess": con.execute("SELECT COUNT(*) FROM preprocess").fetchone()[0],
        "interval_reports": con.execute(
            "SELECT COUNT(*) FROM interval_report"
        ).fetchone()[0],
    }


# Capture columns surfaced by `list` (REQ-DATA-002 / concept §10.13).
_LIST_COLUMNS = ("id", "ts", "active_app", "idle_gap_s", "duration_s")


def list_captures(
    con: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Return capture metadata in ``[start, end)`` (half-open), ordered by ``ts``.

    Bounds are local-naive ISO strings (see :func:`norm.timerange.to_db_ts`); either
    may be ``None`` for an open end.
    """
    sql = f"SELECT {', '.join(_LIST_COLUMNS)} FROM capture"
    clauses, params = [], []
    if start is not None:
        clauses.append("ts >= ?")
        params.append(start)
    if end is not None:
        clauses.append("ts < ?")
        params.append(end)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY ts"
    return [dict(zip(_LIST_COLUMNS, row)) for row in con.execute(sql, params)]


def _atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically and owner-only (temp file, then rename)."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
