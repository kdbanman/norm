"""``norm report`` — summarize captures: preprocess windows and interval reports.

``report preprocess`` slides a K-wide, stride-J window over the stored captures and,
for each window not already summarized, runs the in-process model over the window's
images + AX text and stores the markdown encrypted (PREPROCESS-001..007, concept
§10.8–10.9). ``report interval`` aggregates those window summaries over a time range
into one stored interval report (INTERVAL-001..005, concept §10.10–10.12): it requires
a range, and when the range is not fully covered it either fills the gap (the default
for a non-interactive run, ``--auto-preprocess``, or an interactive yes) or fails with
COVERAGE_MISSING (``--strict`` or a declined prompt).

``--dry-run`` previews the planned work — window count, capture ids, model_ref, and the
effective prompt that *would* reach the model — while loading no model and writing no
rows (REPORT-002). With no subcommand, ``report`` prints usage and exits 2
(REPORT-001).

Inference is reached only through :mod:`norm.inference` (with the ``NORM_FAKE_MODEL``
seam); the window/stride math lives in :mod:`norm.report`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
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
    iv.add_argument("--auto-preprocess", dest="auto_preprocess", action="store_true",
                    help="Summarize any uncovered windows first, without prompting.")
    iv.add_argument("--strict", action="store_true",
                    help="Fail instead of summarizing when the range is not fully covered.")
    iv.add_argument("--output", dest="output", metavar="PATH",
                    help="Write the aggregated markdown to PATH (plaintext) instead of stdout.")
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
    todo = windows if args.force else _uncovered(con, windows)
    if not todo:
        # Every planned window is already summarized: nothing to do, no model loaded
        # (concept §10.9 idempotent re-run).
        print("0 new windows")
        return int(errors.ExitCode.SUCCESS)

    model = inference.load_model(settings.model_ref)
    _summarize_windows(settings, con, key, todo, model)
    store_mod.flush_index(con, settings.paths.index_file, key)
    print(f"{len(todo)} window(s) summarized")
    return int(errors.ExitCode.SUCCESS)


def _uncovered(con, windows):
    """The planned ``windows`` that have no preprocess row yet (the work to do)."""
    return [
        w for w in windows
        if store_mod.preprocess_by_capture_ids(con, report_mod.canonical_ids(w.capture_ids)) is None
    ]


def _summarize_windows(settings, con, key, windows, model) -> None:
    """Run the model over each window and store its markdown summary.

    Shared by ``report preprocess`` and ``report interval``'s gap-fill: the caller
    supplies the loaded ``model`` (reused across windows) and the ``settings`` whose
    ``prompt_text`` selects the prompt — ``prompt_preprocess`` in both cases, since a
    window summary is always a preprocess unit (the interval prompt is applied only
    when aggregating). No index flush here; the caller flushes once.
    """
    blobs_dir = settings.paths.data_dir / session.BLOBS_DIR
    for w in windows:
        images, ax_text = _load_window(con, key, blobs_dir, w)
        markdown = inference.generate(
            model, prompt=settings.prompt_text, images=images,
            ax_text=ax_text, max_tokens=settings.max_tokens,
        )
        markdown_ref = blobs.write_blob(blobs_dir, key, markdown.encode("utf-8"))
        _store_window(con, blobs_dir, w, settings, markdown_ref)


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
    settings = _Settings(args)
    window_k, stride_j = _window_stride(settings, None, None)
    # A missing range is a usage error (exit 2) raised before the store is opened, so
    # it outranks NOT_INITIALIZED/STORE_LOCKED in the precedence (INTERVAL-002).
    window = timerange.parse_range(frm=args.frm, to=args.to, last=args.last, require_range=True)

    con, key = _open_store_keyed(settings.paths)
    try:
        windows = _plan(con, window, window_k, stride_j)
        missing = _uncovered(con, windows)
        if args.dry_run:
            _emit_plan(args, "interval", settings, windows, covered=len(windows) - len(missing))
            return int(errors.ExitCode.SUCCESS)
        return _run_interval(args, settings, con, key, window, windows, missing)
    finally:
        con.close()
        crypto.scrub(key)


def _run_interval(args, settings, con, key, window, windows, missing) -> int:
    """Aggregate the windows' preprocess summaries into one stored interval report.

    When some windows are uncovered, :func:`_resolve_gap` decides whether to fill the
    gap (default / ``--auto-preprocess`` / interactive yes) or fail (``--strict`` /
    declined) — that decision runs *before* the model is loaded so COVERAGE_MISSING
    (exit 5) outranks any MODEL_ERROR (concept §10.10).
    """
    model = None
    if missing:
        _resolve_gap(args, len(missing))
        model = inference.load_model(settings.model_ref)
        _summarize_windows(_Settings(args, prompt_key="prompt_preprocess"), con, key, missing, model)

    source_rows = [
        store_mod.preprocess_by_capture_ids(con, report_mod.canonical_ids(w.capture_ids))
        for w in windows
    ]
    blobs_dir = settings.paths.data_dir / session.BLOBS_DIR
    summaries = [blobs.read_blob(blobs_dir, key, r["markdown_ref"]).decode("utf-8") for r in source_rows]

    if model is None:
        model = inference.load_model(settings.model_ref)
    aggregated = inference.aggregate(
        model, prompt=settings.prompt_text, summaries=summaries, max_tokens=settings.max_tokens,
    )

    markdown_ref = blobs.write_blob(blobs_dir, key, aggregated.encode("utf-8"))
    report_id = store_mod.insert_interval_report(
        con,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        range_from=_range_bound(window.start, windows[0].start),
        range_to=_range_bound(window.end, windows[-1].end),
        model=settings.model_ref,
        prompt_id=settings.prompt_id,
        prompt_text=settings.prompt_text,
        source_preprocess_ids=report_mod.canonical_ids([r["id"] for r in source_rows]),
        markdown_ref=markdown_ref,
    )
    store_mod.flush_index(con, settings.paths.index_file, key)
    _emit_interval(args, aggregated, report_id, source_rows)
    return int(errors.ExitCode.SUCCESS)


def _resolve_gap(args, missing_count: int) -> None:
    """Decide how to handle uncovered windows; return to summarize, or raise to abort.

    Order (concept §10.10): ``--strict`` always aborts with COVERAGE_MISSING (exit 5);
    ``--auto-preprocess`` and any non-interactive run (no TTY, or ``--json``) take the
    default and summarize; an interactive run prompts, defaulting to yes. Declining the
    prompt aborts rather than emit a misleading partial report (INTERVAL-003).
    """
    if args.strict:
        raise errors.coverage_missing(
            "range not fully summarized; run `norm report preprocess` or drop --strict"
        )
    if args.auto_preprocess or not _interactive(args):
        return  # default action for a non-interactive run (REQ-GLOBAL-010)
    print(f"range not fully summarized ({missing_count} window(s)); summarize now? [Y/n] ",
          end="", file=sys.stderr, flush=True)
    if sys.stdin.readline().strip().lower() in ("", "y", "yes"):
        return
    raise errors.coverage_missing("range not fully summarized; declined to summarize")


def _interactive(args) -> bool:
    """True when norm may prompt: a real TTY on stdin and not machine-readable ``--json``."""
    return sys.stdin.isatty() and not getattr(args, "json", False)


def _range_bound(requested, fallback: str) -> str:
    """The stored range bound: the requested instant if any, else the data's own edge.

    ``--to now`` (or ``--from`` alone) can leave one end of the requested range open;
    the row's ``range_from``/``range_to`` are NOT NULL, so an open end falls back to the
    first/last aggregated window's timestamp.
    """
    return timerange.to_db_ts(requested) if requested is not None else fallback


def _emit_interval(args, aggregated: str, report_id: int, source_rows: list[dict]) -> None:
    """Emit the aggregated markdown: to ``--output`` (plaintext file), JSON, or stdout.

    With ``--output`` the markdown is written to the user-requested file and stdout
    carries only the path (INTERVAL-005); the encrypted row is stored either way.
    """
    source_ids = [r["id"] for r in source_rows]
    if args.output:
        Path(args.output).write_text(aggregated, encoding="utf-8")
        if getattr(args, "json", False):
            print(json.dumps({"report_id": report_id, "output": args.output,
                              "source_preprocess_ids": source_ids}))
        else:
            print(args.output)
        return
    if getattr(args, "json", False):
        print(json.dumps({"report_id": report_id, "markdown": aggregated,
                          "source_preprocess_ids": source_ids}))
        return
    sys.stdout.write(aggregated)


# ── shared helpers ────────────────────────────────────────────────────────────


class _Settings:
    """Effective per-run settings: resolved paths, config, and model/prompt selection.

    ``prompt_key`` defaults to the subcommand's own prompt (``args.prompt_key``); the
    interval gap-fill passes ``prompt_preprocess`` to summarize windows with the
    preprocess prompt. The ``--prompt`` override only applies to the command's primary
    prompt, never to the secondary gap-fill one.
    """

    def __init__(self, args: argparse.Namespace, *, prompt_key: str | None = None):
        self.paths = session.resolve_paths(args)
        self._cfg = session.load_config(self.paths)
        self.model_ref = str(self.value("model", args.model))
        key = prompt_key or args.prompt_key
        prompt_flag = args.prompt if key == args.prompt_key else None
        self.prompt_text = str(self.value(key, prompt_flag))
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
