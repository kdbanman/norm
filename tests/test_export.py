"""Black-box acceptance tests for ``norm export`` (REQ-DATA-005).

``export`` decrypts a range of artifacts to a plaintext directory — the
user-requested exception to ciphertext-at-rest (REQ-SEC-001), like ``show
--export`` but range-scoped and covering every artifact type. ``--include`` selects
a subset of ``images,ax,reports`` (default: all); ``reports`` covers BOTH stored
preprocess summaries and stored interval reports.

Captures and report rows are produced through the real CLI (the fake-capture and
``NORM_FAKE_MODEL`` seams), so these stay end-to-end. Report prose is never asserted
on — only file presence, layout, and that the decrypted bytes are real.
"""

from __future__ import annotations

import json

from PIL import Image

from tools.normdev.harness import seed_captures


def _fake_model_env(trace_path):
    return {"NORM_FAKE_MODEL": str(trace_path)}


def _seed_full(store, tmp_path, n=6):
    """Seed ``n`` captures + one preprocess summary + one interval report.

    Exercises every artifact type export can emit: capture image/AX blobs, a
    preprocess-window markdown, and an interval-report markdown.
    """
    store.init()
    seed_captures(store, n, work_dir=tmp_path / "frames")
    pre = store.run("report", "preprocess", extra_env=_fake_model_env(tmp_path / "pre.jsonl"))
    assert pre.returncode == 0, pre.stderr
    iv = store.run("report", "interval", "--last", "24h", extra_env=_fake_model_env(tmp_path / "iv.jsonl"))
    assert iv.returncode == 0, iv.stderr


_WIDE = ("--from", "2000-01-01T00:00:00", "--to", "2100-01-01T00:00:00")


# ── default --include exports all available types ─────────────────────────────


def test_export_default_include_writes_all_types(store, tmp_path):
    # REQ-DATA-005: omitting --include exports images, ax, and reports (both kinds).
    _seed_full(store, tmp_path)
    out = tmp_path / "dump"
    result = store.run("export", *_WIDE, "--out", str(out))
    assert result.returncode == 0, result.stderr

    pngs = sorted((out / "images").glob("*.png"))
    axes = sorted((out / "ax").glob("*.ax.json"))
    pre_md = list((out / "reports" / "preprocess").glob("*.md"))
    iv_md = list((out / "reports" / "interval").glob("*.md"))
    assert len(pngs) == 6
    assert len(axes) == 6
    assert len(pre_md) == 1  # the one preprocess summary
    assert len(iv_md) == 1  # the one interval report

    # The decrypted artifacts are real: the PNG decodes, the AX JSON parses, the
    # markdown is non-empty plaintext.
    img = Image.open(pngs[0])
    img.load()
    assert img.size == (64, 64)
    assert json.loads(axes[0].read_text())
    assert pre_md[0].read_text().strip()
    assert iv_md[0].read_text().strip()


def test_export_artifact_filenames_follow_id_layout(store, tmp_path):
    # REQ-DATA-005: files written as images/<id>.png and ax/<id>.ax.json.
    _seed_full(store, tmp_path)
    ids = {row["id"] for row in store.json_out(store.run("list", "--json"))}
    out = tmp_path / "dump"
    assert store.run("export", *_WIDE, "--out", str(out), "--include", "images,ax").returncode == 0

    assert {int(p.stem) for p in (out / "images").glob("*.png")} == ids
    assert {int(p.name.split(".")[0]) for p in (out / "ax").glob("*.ax.json")} == ids


# ── --include selects a subset of types ───────────────────────────────────────


def test_export_include_images_only(store, tmp_path):
    _seed_full(store, tmp_path)
    out = tmp_path / "dump"
    result = store.run("export", "--out", str(out), "--include", "images")
    assert result.returncode == 0, result.stderr
    assert list((out / "images").glob("*.png"))
    assert not (out / "ax").exists()
    assert not (out / "reports").exists()


def test_export_include_reports_writes_both_summary_kinds(store, tmp_path):
    # REQ-DATA-005: `reports` covers BOTH preprocess summaries and interval reports.
    _seed_full(store, tmp_path)
    out = tmp_path / "dump"
    result = store.run("export", "--out", str(out), "--include", "reports")
    assert result.returncode == 0, result.stderr
    assert list((out / "reports" / "preprocess").glob("*.md"))
    assert list((out / "reports" / "interval").glob("*.md"))
    assert not (out / "images").exists()
    assert not (out / "ax").exists()


def test_export_unknown_include_type_is_usage_error(store, tmp_path):
    store.init()
    result = store.run("export", "--out", str(tmp_path / "d"), "--include", "images,bogus")
    assert result.returncode == 2, result.stderr


# ── range scoping ─────────────────────────────────────────────────────────────


def test_export_past_range_writes_no_captures(store, tmp_path):
    _seed_full(store, tmp_path)
    out = tmp_path / "dump"
    result = store.run(
        "export", "--from", "2000-01-01T00:00:00", "--to", "2000-01-02T00:00:00",
        "--out", str(out), "--include", "images",
    )
    assert result.returncode == 0, result.stderr
    # Nothing recorded in the ancient range, so no image artifacts are written.
    images = out / "images"
    assert not images.exists() or not list(images.glob("*.png"))


# ── store-access contract (fail_if: never succeed while locked) ───────────────


def test_export_locked_exits_3_and_writes_nothing(store, tmp_path):
    _seed_full(store, tmp_path)
    out = tmp_path / "dump"
    result = store.run("export", "--out", str(out), passphrase=None)
    assert result.returncode == 3, result.stderr
    assert not out.exists()  # a locked store produces no plaintext export


def test_export_uninitialized_exits_5(store, tmp_path):
    result = store.run("export", "--out", str(tmp_path / "d"))
    assert result.returncode == 5, result.stderr


def test_export_requires_out(store):
    store.init()
    result = store.run("export", "--last", "24h")
    assert result.returncode == 2, result.stderr
