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
  ``--locked`` runs with no passphrase to exercise the locked-store paths;
* ``--env KEY=VAL`` (repeatable) layers extra environment onto the run, for commands
  that read seams beyond the passphrase — e.g. driving ``passwd`` with
  ``--env NORM_OLD_PASSPHRASE=… --env NORM_NEW_PASSPHRASE=…``. The store is
  provisioned with the fixed harness passphrase (printed in the run banner), so that
  is the ``NORM_OLD_PASSPHRASE`` to hand a rotation.

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
    env: dict[str, str] | None = None,
    argv: list[str],
) -> subprocess.CompletedProcess[str]:
    """Provision ``store`` if needed, then run ``norm <argv>`` against it.

    Returns the command's ``CompletedProcess`` (or the failing ``init``'s, if
    auto-provisioning fails). The passphrase is omitted when ``locked``; ``env``
    layers extra seams on top (and wins over the capture seam on key collisions).
    """
    if not no_init and not store.is_initialized():
        provisioned = store.run("init", "--skip-model", passphrase=PASSPHRASE)
        if provisioned.returncode != 0:
            return provisioned

    extra_env: dict[str, str] = {}
    if capture:
        extra_env.update(capture_env(write_fake_frame(store.base / "frames"), idle=str(idle)))
    if env:
        extra_env.update(env)
    passphrase = None if locked else PASSPHRASE
    return store.run(*argv, passphrase=passphrase, extra_env=extra_env or None)


def main(
    *,
    base: str | None = None,
    keep: bool = False,
    no_init: bool = False,
    capture: bool = False,
    idle: int = 0,
    locked: bool = False,
    env: dict[str, str] | None = None,
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
    # Surface the store's app password: it's the fixed harness constant, not anything
    # the caller chose, so a command needing the *current* password (passwd) knows
    # what to pass as NORM_OLD_PASSPHRASE.
    creds = "locked (no passphrase)" if locked else f"app password: {PASSPHRASE!r}"
    print(f"run store: {root}  [{creds}]", file=sys.stderr)
    try:
        result = run_once(
            NormStore(root),
            no_init=no_init,
            capture=capture,
            idle=idle,
            locked=locked,
            env=env,
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
