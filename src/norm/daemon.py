"""launchd user-agent probe for the record daemon.

norm's recorder runs as a per-user LaunchAgent (gui domain), never a root
LaunchDaemon (REQ-RECORD-009, REQ-SEC-003). The install/start/stop lifecycle lands
with that requirement; for now this exposes the read-only state ``status`` reports.
Until an agent is installed the probe simply reports ``running=False``.
"""

from __future__ import annotations

import os
import subprocess

# launchd label for the user agent (gui/<uid>/<LABEL>).
LABEL = "com.github.norm.recorder"


def is_running() -> bool:
    """True iff the norm LaunchAgent is loaded in the current user's gui domain."""
    try:
        probe = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return probe.returncode == 0
