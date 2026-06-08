"""Tests for the developer tooling under ``tools/normdev``.

These cover the dev CLI itself — the requirements query and the smoke harness —
not any product requirement. They keep the chores that used to be re-derived as
shell one-liners honest: the requirements parser must stay in sync with the doc's
embedded data, and ``smoke`` must actually drive the real CLI green.
"""

from __future__ import annotations

import json

import pytest

from tools.normdev import concept
from tools.normdev import decisions as decs
from tools.normdev import requirements as reqs
from tools.normdev import run as run_mod
from tools.normdev import smoke
from tools.normdev.harness import NormStore


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


# ── run: ad-hoc commands against an ephemeral store ──────────────────────────


def test_run_once_auto_inits_then_executes(tmp_path):
    """First call provisions the store; a second reuses it (no re-init failure)."""
    store = NormStore(tmp_path)
    set_res = run_mod.run_once(store, argv=["config", "set", "interval_minutes", "9"])
    assert set_res.returncode == 0, set_res.stderr
    assert store.is_initialized()

    get_res = run_mod.run_once(store, argv=["config", "get", "interval_minutes"])
    assert get_res.returncode == 0, get_res.stderr
    assert get_res.stdout.strip() == "9"


def test_run_once_no_init_leaves_the_store_uninitialized(tmp_path):
    store = NormStore(tmp_path)
    skipped = run_mod.run_once(store, no_init=True, argv=["list"])
    assert skipped.returncode == 5  # NOT_INITIALIZED — auto-init was skipped
    assert not store.is_initialized()

    provisioned = run_mod.run_once(store, argv=["list"])  # auto-inits this time
    assert provisioned.returncode == 0, provisioned.stderr


def test_run_once_capture_seam_records_a_frame(tmp_path):
    store = NormStore(tmp_path)
    rec = run_mod.run_once(store, capture=True, argv=["record", "--once", "--interval", "1"])
    assert rec.returncode == 0, rec.stderr

    listed = run_mod.run_once(store, argv=["list", "--json"])
    assert listed.returncode == 0, listed.stderr
    assert len(json.loads(listed.stdout)) == 1


def test_run_env_passthrough_drives_passwd(tmp_path):
    """`--env` layers extra seams onto a run — the way passwd is driven manually.

    The store is auto-provisioned with the harness passphrase, so that is the
    NORM_OLD_PASSPHRASE a rotation must supply.
    """
    from tools.normdev.harness import PASSPHRASE

    store = NormStore(tmp_path)
    rotated = run_mod.run_once(
        store,
        argv=["passwd"],
        env={"NORM_OLD_PASSPHRASE": PASSPHRASE, "NORM_NEW_PASSPHRASE": "rotated pw"},
    )
    assert rotated.returncode == 0, rotated.stderr

    # the auto-init password no longer unlocks; the rotated one does.
    assert store.run("list", passphrase=PASSPHRASE).returncode == 3
    assert store.run("list", passphrase="rotated pw").returncode == 0


def test_parse_env_builds_dict_and_rejects_malformed():
    from tools.normdev import __main__ as cli

    assert cli._parse_env(None) is None
    assert cli._parse_env(["A=1", "B=x=y"]) == {"A": "1", "B": "x=y"}  # only first '=' splits
    assert cli._parse_env(["EMPTY="]) == {"EMPTY": ""}  # empty value is allowed
    for bad in (["noequals"], ["=novalue"]):
        with pytest.raises(ValueError):
            cli._parse_env(bad)


@pytest.mark.parametrize("keep,should_exist", [(False, False), (True, True)])
def test_run_main_temp_store_cleanup_honors_keep(tmp_path, monkeypatch, keep, should_exist):
    made = tmp_path / "ephemeral"

    def fake_mkdtemp(*_a, **_k):
        made.mkdir(parents=True, exist_ok=True)
        return str(made)

    monkeypatch.setattr(run_mod.tempfile, "mkdtemp", fake_mkdtemp)
    code = run_mod.main(keep=keep, argv=["config", "path"])
    assert code == 0
    assert made.exists() is should_exist


# ── concept: worked examples cross-linked from `req show` ─────────────────────


def test_subcommands_in_extracts_subcommand_ignoring_flags_and_dotnorm():
    assert concept.subcommands_in("$ norm config set k v") == {"config"}
    assert concept.subcommands_in("norm --json list") == {"list"}
    assert concept.subcommands_in("norm config get x ; norm config path") == {"config"}
    # prose mentioning ~/.norm/... must not be read as a `norm` invocation
    assert concept.subcommands_in("after  ~/.norm/config.toml unchanged") == set()


def test_load_worked_examples_parses_the_concept_doc():
    examples = concept.load_worked_examples()
    assert len(examples) >= 10  # the doc carries the full §10 worked-example set
    config_examples = [e for e in examples if "config" in e.subcommands]
    assert config_examples, "no worked example references `config`"
    assert any(e.section == "§10.17" for e in config_examples)
    assert any("norm config set" in e.body for e in config_examples)


def test_for_requirement_links_the_matching_worked_example():
    req = reqs.find("REQ-CONFIG-001")
    examples = concept.for_requirement(req)
    assert any(e.section == "§10.17" for e in examples)


def test_req_show_includes_the_concept_example(capsys):
    from tools.normdev import __main__ as cli

    code = cli._cmd_req_show("REQ-CONFIG-001")
    out = capsys.readouterr().out
    assert code == 0
    assert "§10.17" in out
    assert "norm config set" in out


# ── decisions: read the ADRs instead of hand-scraping the HTML ────────────────
#
# These pin the behaviour that replaces the ad-hoc "strip tags, take [:4000]"
# heredoc agents kept re-deriving: the reader must load *every* ADR in document
# order, decode HTML entities, and never truncate the tail (the newest ADR).


def test_load_decisions_reads_every_record_in_order():
    rows = decs.load_decisions()
    ids = [d.id for d in rows]
    # Contiguous and ascending from ADR-001 in document order; robust to new ADRs.
    assert len(ids) >= 6
    assert ids == [f"ADR-{n:03d}" for n in range(1, len(ids) + 1)]
    one = rows[0]
    assert one.title.startswith("Encrypted index")  # heading minus the "ADR-001 — " prefix
    assert one.status == "resolved"  # from the <div class="resolution resolved">
    assert one.body  # populated, not empty


def test_decision_bodies_are_decoded_and_free_of_html_chrome():
    corpus = "\n".join(d.body for d in decs.load_decisions())
    # entities are decoded, not left as raw tokens
    for raw in ("&amp;", "&rarr;", "&nbsp;", "&lt;", "&gt;", "&ge;"):
        assert raw not in corpus
    assert "→" in corpus  # &rarr; decoded; proves unescaping ran
    # `&lt;`/`&gt;` in code survive as real angle brackets, not eaten as tags
    assert "ts < end" in corpus
    # ...but structural HTML chrome is gone
    for chrome in ("<div", "<span", "<h2", 'class="resolution"', "</p>"):
        assert chrome not in corpus


def test_decisions_are_not_truncated_head_and_tail_both_present():
    rows = decs.load_decisions()
    bodies = {d.id: d.body for d in rows}
    # the [:4000] hack kept only the head; a deep record (ADR-006) must load in full
    assert "REQ-GLOBAL-002" in bodies["ADR-006"]
    assert "one-liners every session" in bodies["ADR-006"]  # body text, not just heading
    assert "AES-256-GCM" in bodies["ADR-001"]  # head still there too
    # ...and the *last* record in document order loads fully, not as a truncated stub
    assert len(rows[-1].body) > 200
    assert sum(len(b) for b in bodies.values()) > 6000  # well past the 4000-char cut


def test_find_decision_normalizes_input_and_raises_on_miss():
    assert decs.find("ADR-006").id == "ADR-006"
    assert decs.find("adr-6").id == "ADR-006"  # case- and zero-pad-insensitive
    assert decs.find("6").id == "ADR-006"  # bare number is enough
    with pytest.raises(KeyError):
        decs.find("ADR-999")


def test_dec_list_prints_every_record_with_status(capsys):
    from tools.normdev import __main__ as cli

    code = cli._cmd_dec_list()
    out = capsys.readouterr().out
    assert code == 0
    assert "ADR-001" in out and "ADR-006" in out
    assert "[resolved]" in out
    # Count is reported and matches what the reader loaded (robust to new ADRs).
    assert f"{len(decs.load_decisions())} decision record(s)" in out


def test_dec_show_prints_full_untruncated_record(capsys):
    from tools.normdev import __main__ as cli

    code = cli._cmd_dec_show("ADR-006")  # the record the truncating hack dropped
    out = capsys.readouterr().out
    assert code == 0
    assert "ADR-006" in out and "[resolved]" in out
    assert "REQ-GLOBAL-002" in out  # body present, not just the heading
    assert "dev-only CLI" in out


def test_dec_show_unknown_id_returns_2(capsys):
    from tools.normdev import __main__ as cli

    code = cli._cmd_dec_show("ADR-404")
    err = capsys.readouterr().err
    assert code == 2
    assert "ADR-404" in err
