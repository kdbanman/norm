"""Black-box acceptance tests for ``norm record --once`` (the capture engine).

Covers RECORD-001/002/003/004/007/008, ENV-001, and the capture side of
SEC-001/004. Frames are supplied through the hidden ``NORM_FAKE_CAPTURE`` seam so a
test can construct the exact phash / AX combinations the gating logic must act on,
with no macapptree or real screen involved. Idle is scripted via ``NORM_FAKE_IDLE``;
the permission and dependency failures via ``NORM_FORCE_NO_PERMISSION`` /
``NORM_FORCE_NO_MACAPPTREE``.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

# Reuse the index column contract through the CLI; never touch internal state.


def _gradient(*, vertical=False, size=64) -> Image.Image:
    img = Image.new("L", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = (y if vertical else x) * 255 // size
    return img


_BASE_AX = {
    "role": "AXWindow",
    "title": "Editor",
    "children": [{"role": "AXButton", "title": "OK"}],
}


def _make_frame(dir_path: Path, *, image: Image.Image, ax: dict, active_app="TextEdit") -> str:
    """Write an image+AX pair (and app name) for the NORM_FAKE_CAPTURE seam."""
    dir_path.mkdir(parents=True, exist_ok=True)
    image.save(dir_path / "image.png")
    (dir_path / "ax.json").write_text(json.dumps(ax))
    if active_app is not None:
        (dir_path / "active_app.txt").write_text(active_app)
    return str(dir_path)


def _capture_env(frame_dir: str, *, idle="0") -> dict[str, str]:
    return {"NORM_FAKE_CAPTURE": frame_dir, "NORM_FAKE_IDLE": idle}


def _blobs(store) -> list[Path]:
    blob_dir = store.data_dir / "blobs"
    return sorted(p for p in blob_dir.iterdir() if p.is_file()) if blob_dir.exists() else []


def _captures(store):
    result = store.run("list", "--json")
    assert result.returncode == 0, result.stderr
    return store.json_out(result)


# ── RECORD-001 + SEC-001 ───────────────────────────────────────────────────────


def test_record_once_stores_changed_frame(store, tmp_path):
    store.init()
    frame = _make_frame(tmp_path / "f1", image=_gradient(), ax=_BASE_AX)

    result = store.run("record", "--once", "--interval", "1", extra_env=_capture_env(frame))
    assert result.returncode == 0, result.stderr

    rows = _captures(store)
    assert len(rows) == 1
    (row,) = rows
    assert row["active_app"] == "TextEdit"
    assert row["duration_s"] == 60  # interval_minutes(1) * 60
    assert row["idle_gap_s"] == 0

    blobs = _blobs(store)
    assert len(blobs) == 2  # one image, one AX
    for blob in blobs:
        data = blob.read_bytes()
        assert not data.startswith(b"\x89PNG"), "image blob stored in plaintext"
        with pytest.raises(Exception):
            json.loads(data)  # AX blob is not readable JSON
        with pytest.raises(Exception):
            Image.open(BytesIO(data)).load()  # image blob is not a decodable image


# ── RECORD-003 ─────────────────────────────────────────────────────────────────


def test_record_once_dedupes_unchanged_frame(store, tmp_path):
    store.init()
    frame = _make_frame(tmp_path / "f", image=_gradient(), ax=_BASE_AX)

    first = store.run("record", "--once", "--interval", "1", extra_env=_capture_env(frame))
    assert first.returncode == 0, first.stderr
    assert len(_captures(store)) == 1

    second = store.run("record", "--once", "--interval", "1", extra_env=_capture_env(frame))
    assert second.returncode == 0, second.stderr
    assert "duplicate" in (second.stdout + second.stderr).lower()

    rows = _captures(store)
    assert len(rows) == 1  # no new row
    assert rows[0]["duration_s"] == 120  # 60 + another interval
    assert len(_blobs(store)) == 2  # no new blobs


# ── RECORD-004 ─────────────────────────────────────────────────────────────────


def test_record_once_stores_when_only_one_of_phash_or_ax_changes(store, tmp_path):
    store.init()
    img_h, img_v = _gradient(vertical=False), _gradient(vertical=True)
    ax_other = dict(_BASE_AX, title="Browser")

    # 1) baseline frame
    f1 = _make_frame(tmp_path / "a", image=img_h, ax=_BASE_AX)
    assert store.run("record", "--once", extra_env=_capture_env(f1)).returncode == 0
    assert len(_captures(store)) == 1

    # 2) same image, AX changed → stored (dedupe needs BOTH equal)
    f2 = _make_frame(tmp_path / "b", image=img_h, ax=ax_other)
    assert store.run("record", "--once", extra_env=_capture_env(f2)).returncode == 0
    assert len(_captures(store)) == 2

    # 3) image changed, AX unchanged from previous → stored
    f3 = _make_frame(tmp_path / "c", image=img_v, ax=ax_other)
    assert store.run("record", "--once", extra_env=_capture_env(f3)).returncode == 0
    assert len(_captures(store)) == 3


# ── RECORD-002 ─────────────────────────────────────────────────────────────────


def test_record_once_skips_while_idle_and_stamps_gap(store, tmp_path):
    store.init()
    frame = _make_frame(tmp_path / "f", image=_gradient(), ax=_BASE_AX)

    idle = store.run(
        "record", "--once", "--idle-threshold", "1",
        extra_env=_capture_env(frame, idle="180"),
    )
    assert idle.returncode == 0, idle.stderr
    assert "idle" in (idle.stdout + idle.stderr).lower()
    assert _captures(store) == []  # nothing stored while idle
    assert _blobs(store) == []  # no blobs written

    active = store.run("record", "--once", "--interval", "1", extra_env=_capture_env(frame, idle="0"))
    assert active.returncode == 0, active.stderr
    rows = _captures(store)
    assert len(rows) == 1
    assert rows[0]["idle_gap_s"] >= 180  # buffered idle stamped on the next stored capture


# ── RECORD-002 / duration via --interval (REQ-GLOBAL-006 for record) ───────────


def test_record_duration_follows_interval_flag_over_default(store, tmp_path):
    store.init()  # default interval_minutes == 5
    frame = _make_frame(tmp_path / "f", image=_gradient(), ax=_BASE_AX)

    # No --interval ⇒ default 5 min ⇒ 300s.
    assert store.run("record", "--once", extra_env=_capture_env(frame)).returncode == 0
    assert _captures(store)[0]["duration_s"] == 300


# ── RECORD-007 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "which,needle",
    [("screen", "screen recording"), ("ax", "accessibility")],
)
def test_record_once_fails_without_permission(store, tmp_path, which, needle):
    store.init()
    frame = _make_frame(tmp_path / "f", image=_gradient(), ax=_BASE_AX)
    env = _capture_env(frame)
    env["NORM_FORCE_NO_PERMISSION"] = which

    result = store.run("record", "--once", extra_env=env)
    assert result.returncode == 6
    assert needle in result.stderr.lower()
    assert _blobs(store) == []


# ── ENV-001 ────────────────────────────────────────────────────────────────────


def test_record_once_missing_macapptree(store):
    store.init()
    # No NORM_FAKE_CAPTURE: the real backend probe runs and the seam forces it absent.
    result = store.run("record", "--once", extra_env={"NORM_FORCE_NO_MACAPPTREE": "1"})
    assert result.returncode == 6
    assert "macapptree" in result.stderr.lower()


# ── RECORD-008 / SEC-004 ───────────────────────────────────────────────────────


def test_record_once_locked_store(store, tmp_path):
    store.init()
    frame = _make_frame(tmp_path / "f", image=_gradient(), ax=_BASE_AX)

    # No passphrase available: env layer passes (fake capture), auth layer fails.
    result = store.run("record", "--once", passphrase=None, extra_env=_capture_env(frame))
    assert result.returncode == 3
    assert _blobs(store) == []  # nothing read or written while locked


def test_record_once_locked_store_json_envelope(store, tmp_path):
    store.init()
    frame = _make_frame(tmp_path / "f", image=_gradient(), ax=_BASE_AX)

    result = store.run("--json", "record", "--once", passphrase=None, extra_env=_capture_env(frame))
    assert result.returncode == 3
    envelope = json.loads(result.stdout)
    assert envelope["error"]["code"] == "STORE_LOCKED"
    assert envelope["error"]["exit"] == 3


# ── precedence: never-initialized store ────────────────────────────────────────


def test_record_once_not_initialized(store, tmp_path):
    frame = _make_frame(tmp_path / "f", image=_gradient(), ax=_BASE_AX)
    result = store.run("record", "--once", extra_env=_capture_env(frame))
    assert result.returncode == 5
    assert "init" in result.stderr.lower()
    assert _blobs(store) == []


# ── REQ-GLOBAL-005: CLI flag > config file > default ─────────────────────────────


def test_config_interval_overrides_default_when_no_flag(store, tmp_path):
    """A config value is used over the built-in default when no flag is given."""
    store.init()  # default interval_minutes == 5 (⇒ 300s)
    assert store.run("config", "set", "interval_minutes", "9").returncode == 0
    frame = _make_frame(tmp_path / "f", image=_gradient(), ax=_BASE_AX)

    result = store.run("record", "--once", extra_env=_capture_env(frame))
    assert result.returncode == 0, result.stderr
    assert _captures(store)[0]["duration_s"] == 540  # 9 * 60 from config, not 300


def test_record_interval_flag_overrides_config_file(store, tmp_path):
    """REQ-GLOBAL-005: ``--interval 1`` wins over a config interval_minutes of 9."""
    store.init()
    assert store.run("config", "set", "interval_minutes", "9").returncode == 0
    frame = _make_frame(tmp_path / "f", image=_gradient(), ax=_BASE_AX)

    result = store.run("record", "--once", "--interval", "1", extra_env=_capture_env(frame))
    assert result.returncode == 0, result.stderr
    assert _captures(store)[0]["duration_s"] == 60  # CLI 1 min, not config's 9 (540)
