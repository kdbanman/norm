"""Security-invariant guards for the key-custody and privilege model.

These assert *negative-space* contracts — properties the implementation must keep
upholding — so most pass against the current code; their job is to fail the day a
change regresses one (a new Keychain shell-out, a privilege escalation, a plaintext
spill during reporting). Three requirements, three mechanisms:

* REQ-SEC-002 — the login password is never read or held; no macOS Keychain is used.
  The data key is wrapped by the norm *app* password and stored on disk, distinct
  from the login password. Asserted statically (norm imports no Keychain/PAM library
  and shells out to no Keychain/login-auth tool) and behaviorally (``key.json`` is an
  Argon2id wrap openable by the app password alone).
* REQ-SEC-003 — no command needs elevated privileges. Asserted behaviorally (a full
  lifecycle runs green as the unprivileged test user) and statically (no
  setuid/seteuid/sudo, and the recorder probes the per-user ``gui`` launchd domain,
  never a root ``system`` LaunchDaemon).
* REQ-SEC-006 — report-time decryption is transient and in-memory. Asserted both
  black-box (preprocess writes no plaintext image/AX to the data dir *or* an isolated
  TMPDIR) and below-the-CLI (``_load_window`` hands generate() in-memory PIL images
  and touches no disk).

Static guards parse ``src/norm`` with :mod:`ast` rather than grepping text, so the
intentional "no Keychain"/"never a LaunchDaemon" mentions in docstrings don't trip
them — only real imports and call sites count.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from norm import crypto, report as report_mod, session, store as store_mod
from norm.commands import report as report_cmd
from tools.normdev.harness import PASSPHRASE, seed_captures

SRC = Path(__file__).resolve().parent.parent / "src" / "norm"

# Tools norm is permitted to shell out to (both unprivileged, neither Keychain nor
# login-auth): the idle-time probe and the per-user LaunchAgent probe. A new entry
# here must be a conscious decision — that tripwire is the point.
ALLOWED_SUBPROCESS_PROGRAMS = {"ioreg", "launchctl"}

# Surfaces that would mean norm touched the login password or the Keychain.
FORBIDDEN_IMPORTS = {"keyring", "keychain", "pam", "pypam"}
FORBIDDEN_PROGRAMS = {"security", "dscl", "dscacheutil", "login", "sudo", "su"}

# Calls that would drop/raise privilege — a normal-user CLI makes none of them.
PRIVILEGE_CALLS = {"setuid", "seteuid", "setgid", "setegid", "setreuid", "setresuid"}

_SUBPROCESS_FUNCS = {"run", "Popen", "call", "check_call", "check_output"}


# ── static source analysis (shared by the SEC-002 / SEC-003 guards) ──────────────


def _trees() -> list[tuple[Path, ast.Module]]:
    return [(p, ast.parse(p.read_text(encoding="utf-8"))) for p in sorted(SRC.rglob("*.py"))]


def _imported_modules() -> set[str]:
    """Every top-level module name norm's source imports (absolute imports only)."""
    mods: set[str] = set()
    for _, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
    return mods


def _call_program(node: ast.Call) -> str | None:
    """argv[0] of a ``subprocess.*`` / ``os.system`` call, or ``None`` if not one.

    Returns ``"<dynamic>"`` when the program is computed rather than a literal, so the
    forbidden-set check stays sound (a computed program is simply not a known tool).
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return None
    base, attr = func.value.id, func.attr
    is_call = (base == "subprocess" and attr in _SUBPROCESS_FUNCS) or (
        base == "os" and attr in {"system", "popen"}
    )
    if not is_call or not node.args:
        return None
    arg = node.args[0]
    if isinstance(arg, ast.List) and arg.elts:
        arg = arg.elts[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return "<dynamic>"


def _subprocess_programs() -> set[str]:
    progs: set[str] = set()
    for _, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                prog = _call_program(node)
                if prog is not None:
                    progs.add(prog)
    return progs


def _privilege_calls() -> list[tuple[str, str]]:
    """``(file, attr)`` for every ``os.set*id`` call in norm's source."""
    found: list[tuple[str, str]] = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
                and node.func.attr in PRIVILEGE_CALLS
            ):
                found.append((path.name, node.func.attr))
    return found


# ── REQ-SEC-002: no login password, no Keychain ────────────────────────────────


def test_norm_imports_no_keychain_or_login_auth_library():
    leaked = _imported_modules() & FORBIDDEN_IMPORTS
    assert not leaked, f"norm must not import Keychain/login-auth libraries; found {leaked}"


def test_norm_shells_out_to_no_keychain_or_login_tool():
    programs = _subprocess_programs()
    forbidden = programs & FORBIDDEN_PROGRAMS
    assert not forbidden, f"norm must not invoke Keychain/login-auth tools; found {forbidden}"
    # Tripwire: any *new* shell-out must be added to the allowlist deliberately.
    literal = {p for p in programs if p != "<dynamic>"}
    assert literal <= ALLOWED_SUBPROCESS_PROGRAMS, (
        f"unexpected subprocess program(s): {literal - ALLOWED_SUBPROCESS_PROGRAMS}"
    )


def test_data_key_is_argon2id_wrapped_by_app_password_on_disk(store):
    """The data key's custody is an on-disk app-password wrap, not a Keychain item."""
    store.init()
    record = json.loads((store.data_dir / session.KEY_FILE).read_text())
    assert record["kdf"] == "argon2id"

    data_key = crypto.unwrap_data_key(record, PASSPHRASE)
    assert isinstance(data_key, bytes) and len(data_key) == crypto.DATA_KEY_BYTES
    with pytest.raises(crypto.InvalidPassphrase):
        crypto.unwrap_data_key(record, "not the app password")


def test_only_norm_app_password_env_vars_are_recognized():
    """norm's only password inputs are its three app-password vars — never a login one."""
    from norm import passphrase

    recognized = {
        passphrase.ENV_PASSPHRASE,
        passphrase.ENV_OLD_PASSPHRASE,
        passphrase.ENV_NEW_PASSPHRASE,
    }
    assert recognized == {"NORM_PASSPHRASE", "NORM_OLD_PASSPHRASE", "NORM_NEW_PASSPHRASE"}
    assert not any("LOGIN" in name.upper() for name in recognized)


# ── REQ-SEC-003: no elevated privileges ────────────────────────────────────────


def test_full_lifecycle_runs_as_unprivileged_user(store, tmp_path):
    """init → record → preprocess all complete without sudo, as the normal test user."""
    assert os.geteuid() != 0, "the suite must run unprivileged for this guard to mean anything"
    store.init()
    seed_captures(store, 4, work_dir=tmp_path / "frames")
    result = store.run(
        "report", "preprocess", "--window", "2", "--stride", "2",
        extra_env={"NORM_FAKE_MODEL": "1"},
    )
    assert result.returncode == 0, result.stderr


def test_source_makes_no_privilege_escalation_calls():
    assert _privilege_calls() == []
    assert not (_subprocess_programs() & {"sudo", "su"})


def test_source_installs_no_root_owned_launchdaemon():
    # The root-owned daemon directory must never appear in a literal path; the recorder
    # is a per-user LaunchAgent, not a system LaunchDaemon (REQ-SEC-003, REQ-RECORD-009).
    for path in sorted(SRC.rglob("*.py")):
        assert "/Library/LaunchDaemons" not in path.read_text(encoding="utf-8")


def test_daemon_probe_targets_per_user_gui_domain(monkeypatch):
    """``status``'s daemon probe asks the per-user ``gui`` domain, never root ``system``."""
    from norm import daemon

    seen: dict[str, list[str]] = {}

    class _Probe:
        returncode = 1

    def _fake_run(argv, *args, **kwargs):
        seen["argv"] = argv
        return _Probe()

    monkeypatch.setattr(daemon.subprocess, "run", _fake_run)
    daemon.is_running()

    argv = seen["argv"]
    target = argv[-1]
    assert target.startswith(f"gui/{os.getuid()}/"), f"probe target not per-user gui: {target!r}"
    assert "system/" not in target


# ── REQ-SEC-006: report-time decryption is transient and in-memory ─────────────

# Plaintext markers that would betray a decrypted image or AX dump on disk. The
# seeded captures carry AX role/title strings; the stored blobs and index are
# ciphertext, so none of these may appear in any file written under the data dir.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_AX_MARKERS = (b"AXWindow", b"AXButton", b"Window 0", b"Button 0")


def _files_under(*roots: Path) -> list[Path]:
    return [p for root in roots for p in root.rglob("*") if p.is_file()]


def _assert_no_plaintext_capture(files: list[Path]) -> None:
    for f in files:
        data = f.read_bytes()
        assert not data.startswith(_PNG_MAGIC), f"plaintext PNG written to disk: {f}"
        for marker in _AX_MARKERS:
            assert marker not in data, f"plaintext AX ({marker!r}) written to disk: {f}"


def test_preprocess_writes_no_plaintext_image_or_ax_anywhere(store, tmp_path):
    store.init()
    seed_captures(store, 4, work_dir=tmp_path / "frames")

    iso_tmp = tmp_path / "iso_tmp"
    iso_tmp.mkdir()
    result = store.run(
        "report", "preprocess", "--window", "2", "--stride", "2",
        extra_env={
            "NORM_FAKE_MODEL": str(tmp_path / "trace.jsonl"),
            "TMPDIR": str(iso_tmp), "TMP": str(iso_tmp), "TEMP": str(iso_tmp),
        },
    )
    assert result.returncode == 0, result.stderr

    # Nothing plaintext under the data dir (the store) or the isolated temp dir.
    _assert_no_plaintext_capture(_files_under(store.data_dir, iso_tmp))
    # And the temp dir holds no stray plaintext image/AX file at all.
    assert not list(iso_tmp.glob("*.png"))
    assert not list(iso_tmp.glob("*.json"))


def test_load_window_yields_in_memory_pil_images_and_touches_no_disk(store, tmp_path, monkeypatch):
    """Below the CLI: a window's captures decrypt to in-memory PIL images, no disk write."""
    store.init()
    seed_captures(store, 2, work_dir=tmp_path / "frames")

    monkeypatch.setenv("NORM_PASSPHRASE", PASSPHRASE)
    paths = session.resolve_paths(
        SimpleNamespace(config=str(store.config_file), data_dir=str(store.data_dir))
    )
    con, data_key = session.open_store(paths)
    try:
        windows = report_mod.plan_windows(store_mod.list_captures(con), window_k=2, stride_j=1)
        blobs_dir = paths.data_dir / session.BLOBS_DIR

        before = set(paths.data_dir.rglob("*"))
        images, ax_text = report_cmd._load_window(con, bytearray(data_key), blobs_dir, windows[0])
        after = set(paths.data_dir.rglob("*"))

        assert len(images) == 2
        assert all(isinstance(img, Image.Image) for img in images)
        assert isinstance(ax_text, str) and ax_text.strip()
        assert before == after, "decrypting a window must not write anything to disk"
    finally:
        con.close()
