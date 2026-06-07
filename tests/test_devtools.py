"""Tests for the developer tooling under ``tools/normdev``.

These cover the dev CLI itself — the requirements query and the smoke harness —
not any product requirement. They keep the chores that used to be re-derived as
shell one-liners honest: the requirements parser must stay in sync with the doc's
embedded data, and ``smoke`` must actually drive the real CLI green.
"""

from __future__ import annotations

import pytest

from tools.normdev import requirements as reqs
from tools.normdev import smoke


# ── requirements parser ──────────────────────────────────────────────────────


# NB: the coverage heuristic counts any mention of a requirement id under tests/,
# so this file must only ever name *already-covered* real ids (else it would
# falsely mark an outstanding requirement as covered). Negative cases use a
# deliberately fake id.


def test_load_requirements_reads_embedded_data():
    rows = reqs.load_requirements()
    assert len(rows) >= 50  # the doc carries the full spec, not a stub
    ids = {r.id for r in rows}
    assert {"REQ-GLOBAL-001", "REQ-RECORD-001"} <= ids
    assert {"global", "security", "record"} <= {r.category for r in rows}  # breadth
    one = next(r for r in rows if r.id == "REQ-GLOBAL-001")
    assert one.title and one.command and one.pass_if  # fields populated, not empty


def test_find_is_case_insensitive_and_raises_on_miss():
    assert reqs.find("req-record-001").id == "REQ-RECORD-001"
    with pytest.raises(KeyError):
        reqs.find("REQ-NOPE-999")


def test_references_matches_full_and_short_forms(tmp_path):
    (tmp_path / "uses_short.py").write_text("# covers RECORD-001 here\n")
    (tmp_path / "uses_full.py").write_text("# covers REQ-GLOBAL-001 here\n")
    (tmp_path / "unrelated.py").write_text("# nothing relevant\n")

    short_hits = reqs.references("REQ-RECORD-001", tmp_path)
    full_hits = reqs.references("REQ-GLOBAL-001", tmp_path)
    miss = reqs.references("REQ-NOPE-999", tmp_path)

    assert [p.name for p in short_hits] == ["uses_short.py"]
    assert [p.name for p in full_hits] == ["uses_full.py"]
    assert miss == []


# ── smoke harness ────────────────────────────────────────────────────────────


def test_smoke_flow_drives_the_real_cli_green(tmp_path):
    result = smoke.run_smoke(tmp_path, frames=tmp_path / "frames")
    assert result.ok, [label for ok, label in result.checks if not ok]
    assert len(result.checks) == 10  # every scripted step recorded a check
