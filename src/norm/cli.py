"""norm CLI entry point: argument parsing, dispatch, and unified exit codes.

This module is the CLI frontend described in norm-concept.html §4. It owns the
top-level command registry and the global flags; each subcommand's behaviour is
implemented in its own iteration and attached via ``set_defaults(func=...)``.
"""

from __future__ import annotations

import argparse
import sys

from norm import __version__
from norm.commands import init as init_cmd
from norm.commands import list_cmd
from norm.commands import status as status_cmd
from norm.errors import ExitCode, NormError, render_error

# Authoritative top-level command registry: (name, one-line help). Order is the
# order shown in `norm --help` (REQ-GLOBAL-002).
COMMANDS: list[tuple[str, str]] = [
    ("init", "Create the encrypted store and provision the model."),
    ("record", "Capture screenshots + AX trees on a timed loop."),
    ("report", "Summarize captures: preprocess windows or interval reports."),
    ("status", "Show store and daemon state."),
    ("list", "List captures in a time range."),
    ("show", "Show one capture's metadata; optionally export its artifacts."),
    ("export", "Decrypt a range of artifacts to a directory."),
    ("prune", "Delete captures (and optionally reports) before a cutoff."),
    ("config", "Get or set configuration values."),
    ("passwd", "Rotate the app password."),
]


def _add_global_flags(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    """Declare the global flags that may appear before *or* after the subcommand.

    The top-level parser owns the real defaults (``suppress=False``); each
    subparser re-declares the same flags with ``SUPPRESS`` defaults
    (``suppress=True``) so that, when absent after the subcommand, they leave the
    value parsed before it intact instead of resetting it. This lets both
    ``norm --json list`` and ``norm list --json`` work (REQ-DATA-002, REQ-GLOBAL-008).
    """
    def default(value):
        return argparse.SUPPRESS if suppress else value

    parser.add_argument("--config", metavar="PATH", default=default(None),
                        help="Use an alternate config file.")
    parser.add_argument("--data-dir", metavar="PATH", default=default(None),
                        help="Use an alternate data directory.")
    parser.add_argument("--json", action="store_true", default=default(False),
                        help="Emit machine-readable JSON.")
    parser.add_argument("-v", "--verbose", action="count", default=default(0),
                        help="Increase log verbosity.")
    parser.add_argument("-q", "--quiet", action="store_true", default=default(False),
                        help="Suppress non-essential output.")


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with global flags and subcommands."""
    parser = argparse.ArgumentParser(
        prog="norm",
        description=(
            "Local, encrypted screen + AX recorder with in-process "
            "Gemma-4 (mlx-vlm) reporting."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    _add_global_flags(parser, suppress=False)

    # Default handler for any subcommand whose behaviour hasn't been implemented
    # yet. Real subcommands override this via their own set_defaults(func=...).
    parser.set_defaults(func=_unimplemented)

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="<command>",
        required=True,
    )
    parsers = {}
    for name, help_text in COMMANDS:
        sub = subparsers.add_parser(name, help=help_text)
        _add_global_flags(sub, suppress=True)
        parsers[name] = sub

    # Implemented commands configure their own flags + handler; the rest fall back
    # to the _unimplemented default set above.
    init_cmd.configure(parsers["init"])
    status_cmd.configure(parsers["status"])
    list_cmd.configure(parsers["list"])

    return parser


def _unimplemented(args: argparse.Namespace) -> int:
    print(f"norm {args.command}: not implemented yet", file=sys.stderr)
    return ExitCode.RUNTIME_ERROR


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and dispatch. Returns a process exit code.

    Usage errors (no/unknown subcommand, bad arguments) and ``--version`` /
    ``--help`` are handled by argparse, which raises ``SystemExit`` with the
    correct code; that propagates out of ``main`` to terminate the process.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NormError as err:
        render_error(err, json_mode=getattr(args, "json", False))
        return int(err.exit_code)
