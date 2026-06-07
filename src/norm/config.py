"""Configuration: defaults, paths, and reading/writing ``config.toml``.

Effective values resolve as: explicit CLI flag > ``~/.norm/config.toml`` > built-in
default (concept §4). This module owns the defaults and the on-disk config file;
flag-vs-config precedence is applied by each command as it is implemented.

Layout (concept §7):

* ``~/.norm/`` (mode 0700) — ``config.toml`` plus the optional chmod-400 password
  file. The ``--config`` flag points at an alternate config *file*; its parent is
  then the config directory.
* ``data_dir`` (default ``~/Library/Application Support/norm``) — the encrypted
  index, the wrapped data key, and blob files.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

# Defaults mirror norm-requirements conventions.defaults. data_dir is stored
# resolved (see resolve_data_dir) rather than as the literal default string.
DEFAULTS: dict[str, object] = {
    "interval_minutes": 5,
    "idle_threshold_seconds": 300,
    "data_dir": "~/Library/Application Support/norm",
    "phash_threshold": 4,
    "model": "mlx-community/gemma-4-e4b-it-4bit",
    "window_k": 6,
    "stride_j": 3,
    "max_tokens": 512,
    "prompt_preprocess": "What was this user doing?",
    "prompt_interval": "What did the user do over the time interval?",
}

# Authoritative ordered key list (config.toml is written in this order).
CONFIG_KEYS: list[str] = list(DEFAULTS)


def default_config_file() -> Path:
    return Path.home() / ".norm" / "config.toml"


def default_data_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "norm"


def resolve_config_file(flag: str | None) -> Path:
    """The config file in effect: ``--config`` if given, else ``~/.norm/config.toml``."""
    return Path(flag).expanduser() if flag else default_config_file()


def resolve_data_dir(flag: str | None, config: dict | None = None) -> Path:
    """Resolve data_dir by precedence: ``--data-dir`` > config value > default."""
    if flag:
        return Path(flag).expanduser()
    if config and config.get("data_dir"):
        return Path(str(config["data_dir"])).expanduser()
    return default_data_dir()


def read_config(config_file: Path) -> dict:
    """Parse a config TOML file into a dict."""
    return tomllib.loads(Path(config_file).read_text())


def write_config(config_file: Path, values: dict) -> None:
    """Write ``values`` to ``config_file`` as TOML, in CONFIG_KEYS order."""
    ordered = {key: values[key] for key in CONFIG_KEYS if key in values}
    # Preserve any non-standard keys deterministically after the known ones.
    ordered.update({k: v for k, v in values.items() if k not in ordered})
    Path(config_file).write_text(tomli_w.dumps(ordered))


def default_config(data_dir: Path) -> dict:
    """Build a full default config with ``data_dir`` set to the resolved path."""
    config = dict(DEFAULTS)
    config["data_dir"] = str(data_dir)
    return config
