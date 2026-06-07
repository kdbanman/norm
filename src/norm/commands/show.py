"""``norm show`` — one capture's metadata, optionally exporting its artifacts.

``norm show <id>`` prints the capture's metadata (read from the index alone). With
``--export DIR`` it additionally decrypts the capture's image + AX blobs and writes
plaintext copies to ``DIR/<id>.png`` and ``DIR/<id>.ax.json`` — the user-requested
export that is the sole exception to ciphertext-at-rest (REQ-DATA-003, concept
§10.14, REQ-SEC-001). An unknown id is ``UNKNOWN_ID`` (exit 5, REQ-DATA-004),
distinct from a never-initialized store (``NOT_INITIALIZED``, also exit 5) by code.

Decryption is transient and in-memory: blobs are read, written to the requested
files, and never staged as plaintext anywhere else (REQ-SEC-006).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from norm import blobs, errors, session
from norm import store as store_mod


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id", type=int, metavar="ID", help="Capture id (see `norm list`).")
    parser.add_argument(
        "--export", dest="export_dir", metavar="DIR",
        help="Write the decrypted PNG + AX JSON under DIR (plaintext, user-requested).",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    paths = session.resolve_paths(args)
    con, data_key = session.open_store(paths)
    try:
        row = store_mod.get_capture(con, args.id)
        if row is None:
            raise errors.unknown_id(f"capture {args.id} not found")
        # Export before announcing success so a failed decrypt/write surfaces as a
        # non-zero exit rather than alongside "exported" output.
        exported = _export_artifacts(paths, data_key, row, args.export_dir) if args.export_dir else []
    finally:
        con.close()

    meta = {key: row[key] for key in store_mod.META_COLUMNS}
    if getattr(args, "json", False):
        print(json.dumps(meta))
    else:
        _print_human(meta, exported)
    return int(errors.ExitCode.SUCCESS)


def _export_artifacts(paths: session.StorePaths, data_key: bytes, row: dict, dest: str) -> list[Path]:
    """Decrypt the capture's image + AX blobs into ``dest`` and return the paths."""
    blobs_dir = paths.data_dir / session.BLOBS_DIR
    out_dir = Path(dest).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    png = out_dir / f"{row['id']}.png"
    ax = out_dir / f"{row['id']}.ax.json"
    png.write_bytes(blobs.read_blob(blobs_dir, data_key, row["image_ref"]))
    ax.write_bytes(blobs.read_blob(blobs_dir, data_key, row["ax_ref"]))
    return [png, ax]


def _print_human(meta: dict, exported: list[Path]) -> None:
    width = max(len(k) for k in meta)
    for key, value in meta.items():
        print(f"{key:<{width}}  {value if value is not None else '—'}")
    for path in exported:
        print(f"exported  {path}")
