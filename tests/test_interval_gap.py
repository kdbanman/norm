"""Unit tests for ``report interval``'s gap-resolution policy (REQ-INTERVAL-003).

When the range is not fully summarized, :func:`norm.commands.report._resolve_gap`
decides whether to fill the gap or abort. The interactive (TTY) branch can't be
reached through the black-box subprocess tests — their stdin is closed, so there is
never a TTY — so the decision logic is exercised directly here. The non-interactive,
``--strict``, and ``--auto-preprocess`` branches are *also* asserted black-box in
``tests/test_report.py``; this module locks the prompt itself.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from norm.commands import report
from norm.errors import ExitCode, NormError


def _args(**overrides):
    """An args stand-in with the interval flags `_resolve_gap`/`_interactive` read."""
    flags = {"strict": False, "auto_preprocess": False, "json": False, **overrides}
    return SimpleNamespace(**flags)


class _FakeStdin(io.StringIO):
    """A stdin whose `isatty()` is forced, so the prompt branch can be driven."""

    def __init__(self, text: str, *, tty: bool):
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_strict_aborts_with_coverage_missing():
    with pytest.raises(NormError) as exc:
        report._resolve_gap(_args(strict=True), missing_count=2)
    assert exc.value.code == "COVERAGE_MISSING"
    assert exc.value.exit_code == ExitCode.NOT_FOUND


def test_auto_preprocess_summarizes_without_prompting(monkeypatch):
    # --auto-preprocess fills the gap even with a TTY present, never prompting.
    monkeypatch.setattr(report.sys, "stdin", _FakeStdin("n\n", tty=True))
    assert report._resolve_gap(_args(auto_preprocess=True), missing_count=1) is None


def test_non_interactive_takes_default_summarize(monkeypatch):
    monkeypatch.setattr(report.sys, "stdin", _FakeStdin("", tty=False))
    assert report._resolve_gap(_args(), missing_count=1) is None


def test_json_is_treated_as_non_interactive(monkeypatch):
    # Even on a TTY, --json must not prompt (output is machine-readable).
    monkeypatch.setattr(report.sys, "stdin", _FakeStdin("n\n", tty=True))
    assert report._resolve_gap(_args(json=True), missing_count=1) is None


@pytest.mark.parametrize("answer", ["\n", "y\n", "Y\n", "yes\n", "  yes \n"])
def test_interactive_default_yes_summarizes(monkeypatch, answer):
    monkeypatch.setattr(report.sys, "stdin", _FakeStdin(answer, tty=True))
    assert report._resolve_gap(_args(), missing_count=1) is None


@pytest.mark.parametrize("answer", ["n\n", "no\n", "q\n"])
def test_interactive_decline_aborts(monkeypatch, answer):
    monkeypatch.setattr(report.sys, "stdin", _FakeStdin(answer, tty=True))
    with pytest.raises(NormError) as exc:
        report._resolve_gap(_args(), missing_count=1)
    assert exc.value.code == "COVERAGE_MISSING"
