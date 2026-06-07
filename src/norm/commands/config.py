"""``norm config`` — read and write ``~/.norm/config.toml`` (REQ-CONFIG-001/002).

Three actions over the plaintext config file (the file the encrypted store is
independent of, concept §7):

* ``config get KEY``   — print the effective value (config file, else built-in default);
* ``config set KEY V``  — coerce ``V`` to ``KEY``'s type and persist it as valid TOML,
  preserving every other key already present;
* ``config path``      — print the absolute path of the config file in effect.

Unknown keys are a usage error (exit 2) on both get and set; ``set`` rejects before
touching the file, so a bad key leaves ``config.toml`` byte-for-byte unchanged
(REQ-CONFIG-002). Effective values everywhere else resolve flag > config > default
via :func:`norm.config.effective_value`; this command surfaces the config layer.
"""

from __future__ import annotations

import argparse
import json
import os

from norm import config as config_mod
from norm import errors, session


def configure(parser: argparse.ArgumentParser) -> None:
    """Attach the ``get`` / ``set`` / ``path`` actions and the shared handler."""
    actions = parser.add_subparsers(dest="config_action", metavar="<action>", required=True)

    get = actions.add_parser("get", help="Print a configuration value.")
    get.add_argument("key", metavar="KEY", help="Configuration key (see `norm config get`).")

    setp = actions.add_parser("set", help="Set a configuration value.")
    setp.add_argument("key", metavar="KEY", help="Configuration key to write.")
    setp.add_argument("value", metavar="VALUE", help="New value (typed to the key).")

    actions.add_parser("path", help="Print the path of the config file in effect.")

    # One handler for all three actions; the nested subparsers leave func untouched.
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    paths = session.resolve_paths(args)
    if args.config_action == "path":
        return _path(args, paths)
    if args.config_action == "get":
        return _get(args, paths)
    return _set(args, paths)


def _path(args: argparse.Namespace, paths: session.StorePaths) -> int:
    # abspath, not resolve(): make the path absolute without dereferencing symlinks
    # (a `--config ./x` should print $PWD/x, not its symlink target).
    path = os.path.abspath(paths.config_file)
    if getattr(args, "json", False):
        print(json.dumps({"path": path}))
    else:
        print(path)
    return int(errors.ExitCode.SUCCESS)


def _get(args: argparse.Namespace, paths: session.StorePaths) -> int:
    key = _require_known_key(args.key)
    cfg = session.load_config(paths)
    # No per-key CLI flag here, so this collapses to config-file > default — the same
    # precedence helper every command uses, kept in one place (REQ-GLOBAL-006).
    value = config_mod.effective_value(key, None, cfg)
    if getattr(args, "json", False):
        print(json.dumps({"key": key, "value": value}))
    else:
        print(_format(value))
    return int(errors.ExitCode.SUCCESS)


def _set(args: argparse.Namespace, paths: session.StorePaths) -> int:
    key = _require_known_key(args.key)
    try:
        value = config_mod.coerce_value(key, args.value)
    except ValueError as exc:
        raise errors.usage_error(str(exc)) from exc

    # Load-modify-write the whole file so unrelated keys are preserved; the validity
    # checks above run first, so a rejected set never reaches disk (REQ-CONFIG-002).
    cfg = session.load_config(paths)
    cfg[key] = value
    config_mod.write_config(paths.config_file, cfg)

    if getattr(args, "json", False):
        print(json.dumps({"key": key, "value": value}))
    else:
        print(f"{key} = {_format(value)}")
    return int(errors.ExitCode.SUCCESS)


def _require_known_key(key: str) -> str:
    if key not in config_mod.CONFIG_KEYS:
        raise errors.usage_error(f"unknown config key: {key!r}")
    return key


def _format(value: object) -> str:
    """Render a value for human output (TOML-style booleans, plain ints/strings)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
