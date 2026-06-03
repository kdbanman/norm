# 21 — Verifying "no elevated privileges / no privileged helper"

- **Type:** Verification approach
- **Affects:** REQ-SEC-003, REQ-RECORD-009 ("`--install` requires no sudo")

## The gap

"Every command works as a normal user; no setuid helper or privileged daemon installed" is a
**system-state property** verified by auditing process/filesystem state, not by norm's output.

## Options (executable, non-CLI)

- **Run-as-user, no-sudo harness** *(suspected core)* — execute the full command suite as an
  unprivileged user with **no `sudo` available on PATH**; assert each command either succeeds
  or fails for its **documented** reason (never a privilege error).
- **Post-run audits:**
  - `find` the norm install + any files it created for **setuid/setgid** bits → assert none.
  - Assert `record --install` creates a **LaunchAgent** (`~/Library/LaunchAgents/…`, user
    domain) and **not** a `LaunchDaemon` (`/Library/LaunchDaemons`, root); verify with
    `launchctl print gui/<uid>/<label>` vs. a system domain.
  - Assert no root-owned files appear under `data_dir` or the install location.
- **`--install` without sudo** — the launchd registration succeeds in the user GUI domain;
  `--status` shows `running=true` with a pid owned by the user.

## Resolution

TODO
