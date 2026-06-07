"""``norm status`` — report store and daemon state, always exiting 0 (REQ-DATA-001).

status never fails: on a never-initialized machine it reports
``initialized=false``; on a locked store it reports ``locked`` without prompting;
when unlockable it reports counts read from the encrypted index (no blob is
decrypted). The daemon state comes from a read-only launchd probe.
"""

from __future__ import annotations

import argparse
import json

from norm import crypto, daemon, errors, session
from norm import store as store_mod


def configure(parser: argparse.ArgumentParser) -> None:
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    paths = session.resolve_paths(args)
    initialized = session.is_initialized(paths)

    locked: bool | None = None
    counts = {"captures": None, "last_capture": None, "preprocess": None, "interval_reports": None}
    if initialized:
        # Probe non-interactively so status can report state without ever blocking
        # or failing on a missing/incorrect password. Any unlock failure — no
        # password, wrong password, or a corrupt key/index — is reported as
        # "locked"; status must never propagate an error (REQ-DATA-001).
        try:
            con, _ = session.open_store(paths, allow_prompt=False)
            try:
                counts = store_mod.counts(con)
            finally:
                con.close()
            locked = False
        except (errors.NormError, crypto.DecryptionError, ValueError, OSError):
            locked = True

    state = {
        "initialized": initialized,
        "locked": locked,
        "data_dir": str(paths.data_dir),
        "captures": counts["captures"],
        "last_capture": counts["last_capture"],
        "preprocess": counts["preprocess"],
        "interval_reports": counts["interval_reports"],
        "daemon": {"running": daemon.is_running()},
    }

    if getattr(args, "json", False):
        print(json.dumps(state))
    else:
        _print_human(state)
    return int(errors.ExitCode.SUCCESS)


def _print_human(state: dict) -> None:
    def row(label: str, value: object) -> None:
        print(f"{label + ':':<18}{value}")

    if not state["initialized"]:
        row("initialized", "false  (run `norm init`)")
        row("data dir", state["data_dir"])
        return

    row("initialized", "true")
    row("store", "locked" if state["locked"] else "unlocked")
    row("data dir", state["data_dir"])
    if state["locked"]:
        row("captures", "(locked — provide the app password to see counts)")
    else:
        row("captures", state["captures"])
        row("last capture", state["last_capture"] or "—")
        row("preprocess", state["preprocess"])
        row("interval reports", state["interval_reports"])
    row("daemon", "running" if state["daemon"]["running"] else "stopped")
