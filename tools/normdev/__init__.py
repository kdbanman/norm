"""normdev — the repo's developer CLI (``python -m tools.normdev``).

Subcommands:

* ``smoke`` — stand up a throwaway encrypted store and drive the real
  ``norm`` CLI end-to-end through the capture seams, then tear it down.
* ``req`` — query the requirements doc (``norm-requirements.html``): list
  requirements, show one in full, or list the ones no test references yet.

The shared ephemeral-store driver lives in :mod:`tools.normdev.harness` and is
the single source of truth for "drive ``python -m norm`` against an isolated
config + data dir" — the pytest ``store`` fixture uses it too, so a manual smoke
run behaves exactly like the acceptance tests.
"""

from pathlib import Path

# repo root: tools/normdev/__init__.py -> parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]
