"""Black-box acceptance tests for `norm init` (REQ-INIT-001/002/003, REQ-SEC-007).

Each test invokes the real CLI as a subprocess. Ciphertext-at-rest and the
no-Keychain guarantee are checked by inspecting the created files directly (no
norm involved), per the requirements doc verification techniques.
"""

import json
import os
import sqlite3
import stat
import subprocess
import sys

import pytest

PASSPHRASE = "correct horse battery staple"


def _env(passphrase=PASSPHRASE):
    env = {k: v for k, v in os.environ.items() if k != "NORM_PASSPHRASE"}
    if passphrase is not None:
        env["NORM_PASSPHRASE"] = passphrase
    return env


def _paths(tmp_path):
    return tmp_path / ".norm" / "config.toml", tmp_path / "data"


def run_norm(*argv, passphrase=PASSPHRASE):
    """Run `python -m norm` non-interactively (stdin closed)."""
    return subprocess.run(
        [sys.executable, "-m", "norm", *argv],
        capture_output=True,
        text=True,
        env=_env(passphrase),
        stdin=subprocess.DEVNULL,
    )


def run_init(tmp_path, *extra, passphrase=PASSPHRASE):
    config_file, data_dir = _paths(tmp_path)
    result = run_norm(
        "--config", str(config_file),
        "--data-dir", str(data_dir),
        "init", "--skip-model", *extra,
        passphrase=passphrase,
    )
    return result, config_file, data_dir


# ── REQ-INIT-001 / REQ-SEC-007: store, config, wrapped key ────────────────────


def test_init_creates_config_dir_data_dir_and_wrapped_key(tmp_path):
    result, config_file, data_dir = run_init(tmp_path)
    assert result.returncode == 0, result.stderr

    config_dir = config_file.parent
    assert config_dir.is_dir()
    # REQ-SEC-007: ~/.norm is mode 0700.
    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700

    # REQ-INIT-001: config.toml carries all default keys.
    import tomllib

    from norm.config import CONFIG_KEYS

    config = tomllib.loads(config_file.read_text())
    for key in CONFIG_KEYS:
        assert key in config, f"{key} missing from config.toml"

    # data_dir created, encrypted index present.
    assert data_dir.is_dir()
    index = data_dir / "index.db"
    assert index.exists()

    # Argon2id-wrapped data key on disk; no plaintext key or passphrase.
    key_path = data_dir / "key.json"
    assert key_path.exists()
    key_json = json.loads(key_path.read_text())
    assert key_json["kdf"] == "argon2id"
    for field in ("salt", "nonce", "wrapped_key"):
        assert key_json.get(field)
    assert PASSPHRASE not in key_path.read_text()
    # key file is owner-only.
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600

    # stdout reports the config + data_dir paths; passphrase never echoed.
    assert str(data_dir) in result.stdout
    assert PASSPHRASE not in result.stdout
    assert PASSPHRASE not in result.stderr


def test_init_index_is_ciphertext_not_a_readable_sqlite_db(tmp_path):
    _, _, data_dir = run_init(tmp_path)
    index = data_dir / "index.db"
    raw = index.read_bytes()
    assert raw[:16] != b"SQLite format 3\x00"

    con = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            con.execute("SELECT name FROM sqlite_master").fetchall()
    finally:
        con.close()


def test_init_creates_no_keychain_item(tmp_path):
    run_init(tmp_path)
    probe = subprocess.run(
        ["security", "find-generic-password", "-s", "norm:datakey"],
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0, "norm must not create a Keychain item"


# ── REQ-INIT-002: refuse to clobber without --force ───────────────────────────


def test_init_refuses_existing_store_without_force(tmp_path):
    first, config_file, data_dir = run_init(tmp_path)
    assert first.returncode == 0, first.stderr

    index = data_dir / "index.db"
    key_path = data_dir / "key.json"
    index_before = index.read_bytes()
    key_before = key_path.read_bytes()

    second, _, _ = run_init(tmp_path)
    assert second.returncode == 2
    assert "initial" in second.stderr.lower()
    assert "force" in second.stderr.lower()

    # nothing overwritten
    assert index.read_bytes() == index_before
    assert key_path.read_bytes() == key_before


def test_init_force_overwrites_existing_store(tmp_path):
    first, _, data_dir = run_init(tmp_path)
    assert first.returncode == 0
    key_before = (data_dir / "key.json").read_bytes()

    second, _, _ = run_init(tmp_path, "--force")
    assert second.returncode == 0, second.stderr
    # a fresh key is minted (new salt/nonce/wrapping)
    assert (data_dir / "key.json").read_bytes() != key_before


def test_init_json_error_envelope_on_existing_store(tmp_path):
    first, config_file, data_dir = run_init(tmp_path)
    assert first.returncode == 0

    second = run_norm(
        "--json",
        "--config", str(config_file),
        "--data-dir", str(data_dir),
        "init", "--skip-model",
    )
    assert second.returncode == 2
    envelope = json.loads(second.stdout)
    assert envelope["error"]["code"] == "USAGE_ERROR"
    assert envelope["error"]["exit"] == 2
    assert envelope["error"]["message"]


# ── REQ-INIT-003: an app password is always required ──────────────────────────


def test_init_requires_a_password(tmp_path):
    result, config_file, data_dir = run_init(tmp_path, passphrase=None)
    assert result.returncode != 0
    assert result.returncode == 3
    # nothing written
    assert not (data_dir / "index.db").exists()
    assert not (data_dir / "key.json").exists()
