"""Small filesystem helpers shared across the store and blob writers."""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Write ``data`` to ``path`` atomically and owner-only (temp file, then rename).

    The temp file is created with ``mode`` from the start so the bytes are never
    briefly world-readable, and is removed if anything fails before the rename.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
