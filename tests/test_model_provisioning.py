"""Model provisioning + the in-process inference boundary.

``norm init`` is the *only* command that downloads weights; ``record`` and ``report``
read an already-provisioned cache and open no network connection at all. These tests
exercise that handshake through two hidden seams (never product features):

* ``NORM_FAKE_MODEL`` — swaps mlx-vlm load()/generate() for the spy (see test_report).
* ``NORM_FAKE_MODEL_CACHE=<dir>`` — a directory standing in for the Hugging Face
  cache. ``init`` "downloads" by dropping a per-model marker there; ``report`` checks
  for that marker before loading, so the "weights present / absent" branches are
  deterministic and need neither the network nor the multi-GB weights.

Covered:
* REQ-INIT-004     — init provisions the model (``--skip-model`` does not);
                     record/report make no network calls; absent weights at report
                     time fail MODEL_UNAVAILABLE naming `norm init` (exit 4).
* REQ-PREPROCESS-005 — preprocess errors (exit 4) when the model can't be loaded,
                     distinguishing 'not downloaded' from 'invalid model_ref', and
                     commits no partial preprocess row.
* REQ-ARCH-001     — inference is in-process; report opens no socket of any kind.
"""

from __future__ import annotations

import json
import socket

import norm.cli as cli
from tools.normdev.harness import PASSPHRASE, seed_captures


def _counts(store):
    return store.json_out(store.run("status", "--json"))


def _fake_cache_env(cache_dir, *, fake_model: bool = False) -> dict[str, str]:
    env = {"NORM_FAKE_MODEL_CACHE": str(cache_dir)}
    if fake_model:
        env["NORM_FAKE_MODEL"] = "1"
    return env


# ── REQ-INIT-004: init provisions weights; --skip-model does not ───────────────


def test_init_provisions_model_into_cache(store, tmp_path):
    cache = tmp_path / "hfcache"
    result = store.run("init", extra_env=_fake_cache_env(cache))
    assert result.returncode == 0, result.stderr
    # The configured (default) model was "downloaded" into the cache.
    assert list(cache.glob("models--*")), "init must provision the model into the cache"


def test_init_skip_model_provisions_no_weights(store, tmp_path):
    cache = tmp_path / "hfcache"
    result = store.run("init", "--skip-model", extra_env=_fake_cache_env(cache))
    assert result.returncode == 0, result.stderr
    assert not cache.exists() or not list(cache.glob("models--*"))


# ── REQ-INIT-004 / REQ-PREPROCESS-005: absent weights → MODEL_UNAVAILABLE ───────


def test_preprocess_errors_when_weights_not_downloaded(store, tmp_path):
    store.init()  # --skip-model: store exists, no weights
    seed_captures(store, 4, work_dir=tmp_path / "frames")

    empty_cache = tmp_path / "empty_cache"
    empty_cache.mkdir()
    result = store.run(
        "--json", "report", "preprocess", "--window", "2", "--stride", "2",
        extra_env=_fake_cache_env(empty_cache),
    )
    assert result.returncode == 4, result.stderr
    env = json.loads(result.stdout)["error"]
    assert env["code"] == "MODEL_UNAVAILABLE"
    assert env["exit"] == 4
    assert "init" in env["message"].lower()  # names the remedy
    # No partial/empty preprocess row was committed.
    assert _counts(store)["preprocess"] == 0


def test_preprocess_succeeds_after_init_provisions_weights(store, tmp_path):
    cache = tmp_path / "hfcache"
    provisioned = store.run("init", extra_env=_fake_cache_env(cache))
    assert provisioned.returncode == 0, provisioned.stderr
    seed_captures(store, 4, work_dir=tmp_path / "frames")

    # Same cache (weights present) + the generate() spy: the handshake completes.
    result = store.run(
        "report", "preprocess", "--window", "2", "--stride", "2",
        extra_env=_fake_cache_env(cache, fake_model=True),
    )
    assert result.returncode == 0, result.stderr
    assert _counts(store)["preprocess"] >= 1


# ── REQ-PREPROCESS-005: an invalid model_ref is distinguished from absent weights ──


def test_preprocess_invalid_model_ref_errors(store, tmp_path):
    store.init()
    seed_captures(store, 4, work_dir=tmp_path / "frames")
    result = store.run(
        "--json", "report", "preprocess", "--window", "2", "--stride", "2",
        "--model", "not a valid ref",
        extra_env={"NORM_FAKE_MODEL": "1"},
    )
    assert result.returncode == 4, result.stderr
    env = json.loads(result.stdout)["error"]
    assert env["code"] == "INVALID_MODEL_REF"
    assert env["exit"] == 4
    # Distinct from the 'weights not downloaded; run norm init' message.
    assert "init" not in env["message"].lower()
    assert _counts(store)["preprocess"] == 0


# ── REQ-ARCH-001: inference is in-process — report opens no socket ─────────────


def test_report_opens_no_socket(store, tmp_path, monkeypatch):
    """A full report run (load + generate + aggregate) creates no socket at all.

    Run in-process so the socket primitives can be guarded: any ``socket.socket`` /
    ``create_connection`` call during the run fails the test. With the generate() spy
    standing in for mlx-vlm, a clean run touches the encrypted store and PIL only —
    never the network, no listening socket, no model-server connection.
    """
    store.init()
    seed_captures(store, 6, work_dir=tmp_path / "frames")

    monkeypatch.setenv("NORM_PASSPHRASE", PASSPHRASE)
    monkeypatch.setenv("NORM_FAKE_MODEL", "1")

    def _no_network(*args, **kwargs):
        raise AssertionError("report opened a socket — inference must be in-process (REQ-ARCH-001)")

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)

    base = ["--config", str(store.config_file), "--data-dir", str(store.data_dir)]
    assert cli.main([*base, "report", "preprocess", "--window", "2", "--stride", "2"]) == 0
    assert cli.main([*base, "report", "interval", "--last", "24h", "--auto-preprocess"]) == 0
