"""Contractual exit codes.

These values are a stable, black-box contract asserted by the acceptance tests
(see norm-requirements.html, conventions.exit_codes and conventions.exit_precedence).
Never renumber them.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    RUNTIME_ERROR = 1  # unexpected failure during a valid operation
    USAGE_ERROR = 2  # unknown command/subcommand, missing/invalid argument
    AUTH_ERROR = 3  # store locked, wrong or missing app password
    MODEL_ERROR = 4  # weights not downloaded, invalid model_ref, inference failure
    NOT_FOUND = 5  # no captures / no preprocess coverage / unknown id / not initialized
    ENVIRONMENT_ERROR = 6  # missing macOS permission, macapptree unavailable
