"""norm CLI entry point: argument parsing, dispatch, and unified exit codes.

This module is the CLI frontend described in norm-concept.html §4. It owns the
top-level command registry and the global flags; each subcommand's behaviour is
implemented in its own iteration and attached via ``set_defaults(func=...)``.
"""

from __future__ import annotations

import argparse
import sys

from norm import __version__
from norm.errors import ExitCode

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
    # Global flags accepted before the subcommand. Their behaviour is wired up in
    # the iterations that need it; they are declared here so the parser accepts
    # the full documented global-flag contract from the start.
    parser.add_argument(
        "--config", metavar="PATH", help="Use an alternate config file."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="Increase log verbosity."
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress non-essential output."
    )

    # Default handler for any subcommand whose behaviour hasn't been implemented
    # yet. Real subcommands override this via their own set_defaults(func=...).
    parser.set_defaults(func=_unimplemented)

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="<command>",
        required=True,
    )
    for name, help_text in COMMANDS:
        subparsers.add_parser(name, help=help_text)

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
    return args.func(args)
