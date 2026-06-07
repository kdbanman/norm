"""Run one ad-hoc ``norm`` command against an ephemeral store (``normdev run``).

The scriptable companion to ``smoke``: where ``smoke`` drives a *fixed* end-to-end
flow, ``run`` executes whatever ``norm`` command you hand it against a throwaway
store, with the passphrase and (optionally) the fake-capture seam already wired in.
It is the durable replacement for hand-rolling ``mkdir /tmp/x; export NORM_PASSPHRASE;
norm --config … init; norm --config … <cmd>`` when poking at a new subcommand.

* ``--base DIR`` reuses/persists a store across calls (a manual poke-session);
  otherwise a temp store is made and removed afterwards (``--keep`` to retain it).
* the store is auto-provisioned on first use (``--no-init`` to skip, e.g. to observe
  not-initialized behaviour or to run ``init`` yourself);
* ``--capture`` injects a fabricated frame so ``record`` works with no real screen;
  ``--locked`` runs with no passphrase to exercise the locked-store paths.

The norm command's stdout is forwarded verbatim (normdev's own chatter goes to
stderr), so ``normdev run config get interval_minutes`` stays pipeable.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.normdev.harness import PASSPHRASE, NormStore, capture_env, write_fake_frame


def run_once(
    store: NormStore,
    *,
    no_init: bool = False,
    capture: bool = False,
    idle: int = 0,
    locked: bool = False,
    argv: list[str],
) -> subprocess.CompletedProcess[str]:
    """Provision ``store`` if needed, then run ``norm <argv>`` against it.

    Returns the command's ``CompletedProcess`` (or the failing ``init``'s, if
    auto-provisioning fails). The passphrase is omitted when ``locked``.
    """
    if not no_init and not store.is_initialized():
        provisioned = store.run("init", "--skip-model", passphrase=PASSPHRASE)
        if provisioned.returncode != 0:
            return provisioned

    extra_env = capture_env(write_fake_frame(store.base / "frames"), idle=str(idle)) if capture else None
    passphrase = None if locked else PASSPHRASE
    return store.run(*argv, passphrase=passphrase, extra_env=extra_env)


def main(
    *,
    base: str | None = None,
    keep: bool = False,
    no_init: bool = False,
    capture: bool = False,
    idle: int = 0,
    locked: bool = False,
    argv: list[str],
) -> int:
    """Set up the store (temp unless ``base``), run the command, forward its output."""
    if argv and argv[0] == "--":  # tolerate `normdev run -- norm-args…`
        argv = argv[1:]
    if not argv:
        print("normdev run: no norm command given", file=sys.stderr)
        return 2

    created = base is None
    root = Path(base) if base else Path(tempfile.mkdtemp(prefix="norm-run-"))
    root.mkdir(parents=True, exist_ok=True)
    print(f"run store: {root}", file=sys.stderr)
    try:
        result = run_once(
            NormStore(root),
            no_init=no_init,
            capture=capture,
            idle=idle,
            locked=locked,
            argv=list(argv),
        )
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode
    finally:
        # A reused/named store (--base) is always kept; a temp store only with --keep.
        if keep or not created:
            print(f"\nleaving store in place: {root}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)
