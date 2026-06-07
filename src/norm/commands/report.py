"""``norm report`` — summarize captures: preprocess windows and interval reports.

``report preprocess`` slides a K-wide, stride-J window over the stored captures and,
for each window not already summarized, runs the in-process model over the window's
images + AX text and stores the markdown encrypted (PREPROCESS-001..007, concept
§10.8–10.9). ``report interval`` aggregates those window summaries over a time range
(concept §10.10–10.12); its full run lands in a later iteration, but ``--dry-run`` is
available now.

``--dry-run`` previews the planned work — window count, capture ids, model_ref, and the
effective prompt that *would* reach ``generate()`` — while loading no model and writing
no rows (REPORT-002). With no subcommand, ``report`` prints usage and exits 2
(REPORT-001).

Inference is reached only through :mod:`norm.inference` (with the ``NORM_FAKE_MODEL``
seam); the window/stride math lives in :mod:`norm.report`.
"""

from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

from norm import blobs, config as config_mod, crypto, errors, inference
from norm import report as report_mod
from norm import session, timerange
from norm import store as store_mod


def configure(parser: argparse.ArgumentParser) -> None:
    """Attach the ``preprocess`` / ``interval`` subcommands and their flags.

    The nested subparser is ``required``: ``norm report`` with no subcommand is a
    usage error whose help names both subcommands (REPORT-001).
    """
    sub = parser.add_subparsers(dest="report_command", required=True)

    pre = sub.add_parser("preprocess", help="Summarize sliding capture windows.")
    _add_global_flags(pre)
    pre.add_argument("--window", dest="window_k", type=int, metavar="K",
                     help="Captures per window (config: window_k).")
    pre.add_argument("--stride", dest="stride_j", type=int, metavar="J",
                     help="Captures the window advances each step (config: stride_j).")
    _add_model_flags(pre, prompt_key="prompt_preprocess")
    _add_range_flags(pre)
    pre.add_argument("--force", action="store_true",
                     help="Recompute and overwrite already-summarized windows.")
    pre.add_argument("--dry-run", action="store_true",
                     help="Preview the planned work; load no model and write no rows.")
    pre.set_defaults(func=run_preprocess)

    iv = sub.add_parser("interval", help="Aggregate window summaries over a time range.")
    _add_global_flags(iv)
    _add_model_flags(iv, prompt_key="prompt_interval")
    _add_range_flags(iv)
    iv.add_argument("--dry-run", action="store_true",
                    help="Preview the planned work; load no model and write no rows.")
    iv.set_defaults(func=run_interval)


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    # Re-declare the global flags on the nested subparsers (deferred import avoids a
    # cli↔command import cycle) so `norm report preprocess --json` parses like every
    # other subcommand (REQ-GLOBAL-008).
    from norm.cli import _add_global_flags as add

    add(parser, suppress=True)


def _add_model_flags(parser: argparse.ArgumentParser, *, prompt_key: str) -> None:
    parser.add_argument("--model", dest="model", metavar="REF",
                        help="MLX model ref to run (config: model).")
    parser.add_argument("--prompt", dest="prompt", metavar="TEXT",
                        help=f"Override the effective prompt (config: {prompt_key}).")
    parser.add_argument("--max-tokens", dest="max_tokens", type=int, metavar="N",
                        help="Max new tokens to generate (config: max_tokens).")
    parser.set_defaults(prompt_key=prompt_key)


def _add_range_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from", dest="frm", metavar="WHEN", help="Range start.")
    parser.add_argument("--to", dest="to", metavar="WHEN", help="Range end (defaults to now).")
    parser.add_argument("--last", dest="last", metavar="DURATION",
                        help="A window ending now, e.g. 24h, 7d.")
    timerange.allow_relative_time_values(parser)


# ── preprocess ────────────────────────────────────────────────────────────────


def run_preprocess(args: argparse.Namespace) -> int:
    settings = _Settings(args)
    window_k, stride_j = _window_stride(settings, args.window_k, args.stride_j)
    window = timerange.parse_range(frm=args.frm, to=args.to, last=args.last)

    con, key = _open_store_keyed(settings.paths)
    try:
        windows = _plan(con, window, window_k, stride_j)
        if args.dry_run:
            _emit_plan(args, "preprocess", settings, windows)
            return int(errors.ExitCode.SUCCESS)
        return _run_preprocess_windows(args, settings, con, key, windows)
    finally:
        con.close()
        crypto.scrub(key)


def _run_preprocess_windows(args, settings, con, key, windows) -> int:
    todo = windows if args.force else [
        w for w in windows
        if store_mod.preprocess_by_capture_ids(con, report_mod.canonical_ids(w.capture_ids)) is None
    ]
    if not todo:
        # Every planned window is already summarized: nothing to do, no model loaded
        # (concept §10.9 idempotent re-run).
        print("0 new windows")
        return int(errors.ExitCode.SUCCESS)

    blobs_dir = settings.paths.data_dir / session.BLOBS_DIR
    model = inference.load_model(settings.model_ref)
    for w in todo:
        images, ax_text = _load_window(con, key, blobs_dir, w)
        markdown = inference.generate(
            model, prompt=settings.prompt_text, images=images,
            ax_text=ax_text, max_tokens=settings.max_tokens,
        )
        markdown_ref = blobs.write_blob(blobs_dir, key, markdown.encode("utf-8"))
        _store_window(con, blobs_dir, w, settings, markdown_ref)
    store_mod.flush_index(con, settings.paths.index_file, key)
    print(f"{len(todo)} window(s) summarized")
    return int(errors.ExitCode.SUCCESS)


def _load_window(con, key, blobs_dir, window):
    """Decrypt a window's captures into in-memory PIL images + concatenated AX text.

    Both modalities are returned so generate() receives images *and* AX text together
    (PREPROCESS-002). Decryption is transient and in-memory (REQ-SEC-006).
    """
    images, ax_parts = [], []
    for capture_id in window.capture_ids:
        row = store_mod.get_capture(con, capture_id)
        png = blobs.read_blob(blobs_dir, key, row["image_ref"])
        images.append(Image.open(BytesIO(png)).convert("RGB"))
        ax_parts.append(blobs.read_blob(blobs_dir, key, row["ax_ref"]).decode("utf-8"))
    return images, "\n".join(ax_parts)


def _store_window(con, blobs_dir, window, settings, markdown_ref: str) -> None:
    """Insert the window's summary row, or overwrite an existing one under ``--force``."""
    ids = report_mod.canonical_ids(window.capture_ids)
    existing = store_mod.preprocess_by_capture_ids(con, ids)
    if existing is not None:
        _unlink_blob(blobs_dir, existing["markdown_ref"])  # drop the stale markdown blob
        store_mod.update_preprocess(
            con, existing["id"], window_start=window.start, window_end=window.end,
            model=settings.model_ref, prompt_id=settings.prompt_id,
            prompt_text=settings.prompt_text, markdown_ref=markdown_ref,
        )
    else:
        store_mod.insert_preprocess(
            con, window_start=window.start, window_end=window.end, capture_ids=ids,
            model=settings.model_ref, prompt_id=settings.prompt_id,
            prompt_text=settings.prompt_text, markdown_ref=markdown_ref,
        )


# ── interval ──────────────────────────────────────────────────────────────────


def run_interval(args: argparse.Namespace) -> int:
    if not args.dry_run:
        # The full aggregation run (INTERVAL-001..005) lands in a later iteration.
        print("norm report interval: not implemented yet (use --dry-run to preview)",
              file=sys.stderr)
        return int(errors.ExitCode.RUNTIME_ERROR)

    settings = _Settings(args)
    window_k, stride_j = _window_stride(settings, None, None)
    window = timerange.parse_range(frm=args.frm, to=args.to, last=args.last, require_range=True)

    con, key = _open_store_keyed(settings.paths)
    try:
        windows = _plan(con, window, window_k, stride_j)
        covered = sum(
            1 for w in windows
            if store_mod.preprocess_by_capture_ids(con, report_mod.canonical_ids(w.capture_ids))
        )
        _emit_plan(args, "interval", settings, windows, covered=covered)
        return int(errors.ExitCode.SUCCESS)
    finally:
        con.close()
        crypto.scrub(key)


# ── shared helpers ────────────────────────────────────────────────────────────


class _Settings:
    """Effective per-run settings: resolved paths, config, and model/prompt selection."""

    def __init__(self, args: argparse.Namespace):
        self.paths = session.resolve_paths(args)
        self._cfg = session.load_config(self.paths)
        self.model_ref = str(self.value("model", args.model))
        self.prompt_text = str(self.value(args.prompt_key, args.prompt))
        self.prompt_id = inference.prompt_id(self.prompt_text)
        self.max_tokens = int(self.value("max_tokens", args.max_tokens))

    def value(self, key: str, flag_value):
        """One config key by precedence: CLI flag > config file > default (REQ-GLOBAL-006)."""
        return config_mod.effective_value(key, flag_value, self._cfg)


def _window_stride(settings: _Settings, window_flag, stride_flag) -> tuple[int, int]:
    """Resolve and validate the window/stride, as a usage error *before* store access.

    plan_windows guards these too, but it runs after the store is unlocked; validating
    here keeps a usage error (exit 2) ahead of an auth error (exit 3) in the precedence
    (conventions.exit_precedence), matching how the range flags are parsed up front.
    """
    window_k = int(settings.value("window_k", window_flag))
    stride_j = int(settings.value("stride_j", stride_flag))
    if window_k < 1 or stride_j < 1:
        raise errors.usage_error("--window and --stride must be >= 1")
    return window_k, stride_j


def _open_store_keyed(paths):
    """Open the store, returning ``(con, key)`` with the data key in a scrubbable buffer.

    Surfaces the NOT_INITIALIZED (5) → STORE_LOCKED (3) precedence via
    :func:`session.open_store`; the buffer lets the caller zero the key on exit.
    """
    con, data_key = session.open_store(paths)
    key = bytearray(data_key)
    return con, key


def _plan(con, window: timerange.TimeRange, window_k: int, stride_j: int):
    start = timerange.to_db_ts(window.start) if window.start else None
    end = timerange.to_db_ts(window.end) if window.end else None
    captures = store_mod.list_captures(con, start, end)
    return report_mod.plan_windows(captures, window_k, stride_j)


def _emit_plan(args, kind, settings: _Settings, windows, *, covered: int | None = None) -> None:
    """Print the dry-run preview: window count, capture ids, model_ref, effective prompt.

    No model is loaded and no row is written before reaching here (REPORT-002).
    """
    all_ids = sorted({cid for w in windows for cid in w.capture_ids})
    if getattr(args, "json", False):
        out = {
            "dry_run": True,
            "command": kind,
            "model": settings.model_ref,
            "prompt": settings.prompt_text,
            "prompt_id": settings.prompt_id,
            "windows": len(windows),
            "capture_ids": all_ids,
            "window_capture_ids": [list(w.capture_ids) for w in windows],
        }
        if covered is not None:
            out["covered_windows"] = covered
        print(json.dumps(out))
        return

    print(f"dry-run: report {kind} (no model loaded, no rows written)")
    print(f"model    {settings.model_ref}")
    print(f"prompt   {settings.prompt_text}")
    print(f"windows  {len(windows)}")
    if covered is not None:
        print(f"covered  {covered} of {len(windows)} already summarized")
    for i, w in enumerate(windows, 1):
        print(f"  window {i}  captures {','.join(str(c) for c in w.capture_ids)}")


def _unlink_blob(blobs_dir, ref: str) -> None:
    try:
        (Path(blobs_dir) / ref).unlink()
    except OSError:
        pass
