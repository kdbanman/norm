"""Contractual exit codes, stable error codes, and the failure-rendering surface.

Exit codes and the ``--json`` error envelope
(``{"error":{"code","exit","message"}}``) are a stable, black-box contract asserted
by the acceptance tests (norm-requirements conventions.exit_codes, error_codes,
json_errors). Never renumber the exit codes or rename the error codes.

Commands raise :class:`NormError`; :func:`render_error` turns it into the
human-readable line (stderr) or the JSON envelope (stdout under ``--json``).
"""

from __future__ import annotations

import json
import sys
from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    RUNTIME_ERROR = 1  # unexpected failure during a valid operation
    USAGE_ERROR = 2  # unknown command/subcommand, missing/invalid argument
    AUTH_ERROR = 3  # store locked, wrong or missing app password
    MODEL_ERROR = 4  # weights not downloaded, invalid model_ref, inference failure
    NOT_FOUND = 5  # no captures / no preprocess coverage / unknown id / not initialized
    ENVIRONMENT_ERROR = 6  # missing macOS permission, macapptree unavailable


class NormError(Exception):
    """A failure with a stable error code and the exit code it maps to."""

    def __init__(self, code: str, exit_code: ExitCode, message: str):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.message = message


# Factories for the documented (conventions.error_codes) failure cases. Keeping the
# code↔exit pairing here prevents drift between call sites.
def usage_error(message: str) -> NormError:
    return NormError("USAGE_ERROR", ExitCode.USAGE_ERROR, message)


def store_locked(message: str) -> NormError:
    return NormError("STORE_LOCKED", ExitCode.AUTH_ERROR, message)


def not_initialized(message: str) -> NormError:
    return NormError("NOT_INITIALIZED", ExitCode.NOT_FOUND, message)


def unknown_id(message: str) -> NormError:
    return NormError("UNKNOWN_ID", ExitCode.NOT_FOUND, message)


def permission_missing(message: str) -> NormError:
    return NormError("PERMISSION_MISSING", ExitCode.ENVIRONMENT_ERROR, message)


def macapptree_missing(message: str) -> NormError:
    return NormError("MACAPPTREE_MISSING", ExitCode.ENVIRONMENT_ERROR, message)


def render_error(err: NormError, *, json_mode: bool) -> None:
    """Emit ``err`` — JSON envelope on stdout under ``--json``, else stderr prose."""
    if json_mode:
        envelope = {"error": {"code": err.code, "exit": int(err.exit_code), "message": err.message}}
        print(json.dumps(envelope))
    else:
        print(f"norm: {err.message}", file=sys.stderr)
