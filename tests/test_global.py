"""Black-box acceptance tests for the global CLI contract (REQ-GLOBAL-001..004).

Each test invokes the real CLI as a separate process so that argv handling and the
process exit code — both contractual — are exercised end to end.
"""

import re
import subprocess
import sys

import pytest

# Top-level commands the CLI must expose (norm-requirements REQ-GLOBAL-002).
COMMANDS = [
    "init",
    "record",
    "report",
    "status",
    "list",
    "show",
    "export",
    "prune",
    "config",
    "passwd",
]


def run_norm(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke `python -m norm <args>` and capture stdout/stderr/exit code."""
    return subprocess.run(
        [sys.executable, "-m", "norm", *args],
        capture_output=True,
        text=True,
    )


def test_version_flag_prints_semver_to_stdout():
    """REQ-GLOBAL-001: `norm --version` -> semver on stdout, exit 0, empty stderr."""
    result = run_norm("--version")
    assert result.returncode == 0
    assert re.search(r"\b\d+\.\d+\.\d+\b", result.stdout), result.stdout
    assert result.stderr == ""


def test_top_level_help_lists_every_command():
    """REQ-GLOBAL-002: `norm --help` lists all documented commands, exit 0."""
    result = run_norm("--help")
    assert result.returncode == 0
    for command in COMMANDS:
        assert command in result.stdout, f"{command!r} missing from help:\n{result.stdout}"


def test_no_subcommand_prints_usage_and_fails():
    """REQ-GLOBAL-003: bare `norm` -> usage on stderr, exit 2."""
    result = run_norm()
    assert result.returncode == 2
    assert "usage" in result.stderr.lower(), result.stderr


def test_unknown_command_is_usage_error():
    """REQ-GLOBAL-004: `norm frobnicate` -> names the command as unknown, exit 2."""
    result = run_norm("frobnicate")
    assert result.returncode == 2
    assert "frobnicate" in result.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
