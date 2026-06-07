"""Black-box acceptance tests for ``norm config`` (REQ-CONFIG-001, REQ-CONFIG-002).

The config file is plaintext TOML at ``~/.norm/config.toml`` (here, the store's
isolated ``--config`` path), independent of the encrypted store. Tests assert on the
CLI's stdout/exit code and on the resulting TOML, never on internal state.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

# ── REQ-CONFIG-001: set/get/path round-trip ─────────────────────────────────────


def test_config_set_writes_valid_toml_and_preserves_other_keys(store):
    store.init()  # writes config.toml with the full defaults (the precondition)

    result = store.run("config", "set", "interval_minutes", "10")
    assert result.returncode == 0, result.stderr

    cfg = tomllib.loads(store.config_file.read_text())  # parses ⇒ still valid TOML
    assert cfg["interval_minutes"] == 10
    assert cfg["interval_minutes"] == int(cfg["interval_minutes"])  # typed int, not "10"
    # Setting one key must not drop the other defaults init wrote.
    assert "idle_threshold_seconds" in cfg
    assert "model" in cfg


def test_config_get_reflects_the_value_just_set(store):
    store.init()
    assert store.run("config", "set", "interval_minutes", "10").returncode == 0

    result = store.run("config", "get", "interval_minutes")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "10"


def test_config_path_prints_the_absolute_config_file_path(store):
    store.init()

    result = store.run("config", "path")
    assert result.returncode == 0, result.stderr

    printed = Path(result.stdout.strip())
    assert printed.is_absolute()
    assert printed == store.config_file


# ── REQ-CONFIG-002: unknown keys are rejected ────────────────────────────────────


def test_config_set_rejects_unknown_key_without_touching_the_file(store):
    store.init()
    before = store.config_file.read_text()

    result = store.run("config", "set", "bogus_key", "1")
    assert result.returncode == 2
    assert "bogus_key" in result.stderr
    assert store.config_file.read_text() == before  # config.toml unchanged
