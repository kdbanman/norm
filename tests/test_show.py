"""Black-box acceptance tests for ``norm show`` (REQ-DATA-003, REQ-DATA-004).

``show`` surfaces one capture's metadata and, with ``--export``, writes decrypted
copies of its image + AX artifacts (the only user-requested plaintext exception to
REQ-SEC-001). It rides the same store-access contract as ``list`` (NOT_INITIALIZED
vs STORE_LOCKED) and adds the unknown-id case (exit 5, UNKNOWN_ID).

Captures are produced through the real ``record --once`` path (the fake-capture
seam), so these stay end-to-end: a frame is recorded, then shown/exported through
the CLI exactly as a user would.
"""

from __future__ import annotations

import json

from PIL import Image

# ── capture helpers (a frame recorded through the real CLI) ────────────────────

_AX = {"role": "AXWindow", "title": "Editor", "children": [{"role": "AXButton"}]}


def _gradient(size=64) -> Image.Image:
    img = Image.new("L", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = x * 255 // size
    return img


def _make_frame(dir_path, *, active_app="TextEdit"):
    dir_path.mkdir(parents=True, exist_ok=True)
    _gradient().save(dir_path / "image.png")
    (dir_path / "ax.json").write_text(json.dumps(_AX))
    (dir_path / "active_app.txt").write_text(active_app)
    return {"NORM_FAKE_CAPTURE": str(dir_path), "NORM_FAKE_IDLE": "0"}


def _record_one(store, tmp_path, *, active_app="TextEdit") -> int:
    """Record a single capture and return its id (via ``list --json``)."""
    env = _make_frame(tmp_path / "frame", active_app=active_app)
    rec = store.run("record", "--once", "--interval", "1", extra_env=env)
    assert rec.returncode == 0, rec.stderr
    rows = store.json_out(store.run("list", "--json"))
    assert len(rows) == 1
    return rows[0]["id"]


# ── REQ-DATA-004: unknown id ───────────────────────────────────────────────────


def test_show_unknown_id_exits_5(store):
    store.init()
    result = store.run("show", "99999999")
    assert result.returncode == 5, result.stderr
    assert "not found" in result.stderr.lower()


def test_show_unknown_id_json_envelope(store):
    store.init()
    result = store.run("--json", "show", "99999999")
    assert result.returncode == 5
    env = json.loads(result.stdout)["error"]
    assert env["code"] == "UNKNOWN_ID"
    assert env["exit"] == 5
    assert env["message"]


def test_show_unknown_id_with_export_writes_nothing(store, tmp_path):
    store.init()
    out = tmp_path / "out"
    result = store.run("show", "99999999", "--export", str(out))
    assert result.returncode == 5, result.stderr
    assert not out.exists()  # a missing id never produces an export dir


# ── REQ-DATA-003: metadata ─────────────────────────────────────────────────────


def test_show_prints_metadata(store, tmp_path):
    store.init()
    cid = _record_one(store, tmp_path, active_app="Safari")
    result = store.run("show", str(cid))
    assert result.returncode == 0, result.stderr
    assert str(cid) in result.stdout
    assert "Safari" in result.stdout


def test_show_json_metadata(store, tmp_path):
    store.init()
    cid = _record_one(store, tmp_path, active_app="Safari")
    result = store.run("--json", "show", str(cid))
    assert result.returncode == 0, result.stderr
    meta = json.loads(result.stdout)
    assert meta["id"] == cid
    assert meta["active_app"] == "Safari"
    assert meta["duration_s"] == 60
    for key in ("ts", "idle_gap_s", "phash", "ax_hash"):
        assert key in meta


# ── REQ-DATA-003: --export decrypts artifacts to disk ──────────────────────────


def test_show_export_writes_decrypted_artifacts(store, tmp_path):
    store.init()
    cid = _record_one(store, tmp_path)
    out = tmp_path / "out"
    result = store.run("show", str(cid), "--export", str(out))
    assert result.returncode == 0, result.stderr

    png = out / f"{cid}.png"
    ax = out / f"{cid}.ax.json"
    assert png.exists() and ax.exists()

    # The PNG is real, decodable image data (round-tripped through encryption).
    img = Image.open(png)
    img.load()
    assert img.size == (64, 64)
    # The AX JSON parses and matches what was captured.
    assert json.loads(ax.read_text()) == _AX


# ── store-access contract (mirrors list; cross-cut REQ-GLOBAL-007/008) ─────────


def test_show_uninitialized_exits_5_not_initialized(store):
    result = store.run("--json", "show", "1")
    assert result.returncode == 5
    assert json.loads(result.stdout)["error"]["code"] == "NOT_INITIALIZED"


def test_show_locked_exits_3(store):
    store.init()
    result = store.run("show", "1", passphrase=None)
    assert result.returncode == 3, result.stderr
    assert "lock" in result.stderr.lower()


def test_show_non_integer_id_is_usage_error(store):
    store.init()
    result = store.run("show", "not-a-number")
    assert result.returncode == 2, result.stderr
