"""Black-box acceptance tests for `norm passwd` (REQ-SEC-005).

Rotation re-wraps the data key with a new app password: the old password must stop
unlocking the store and the new one must start. Verified end-to-end through the CLI
(`list` is the unlock probe — it needs an unlockable store but decrypts no blobs),
plus a direct look at key.json for the no-plaintext-key invariant.
"""

import json
import stat

from tools.normdev.harness import PASSPHRASE

NEW = "a brand new passphrase"


def _passwd_env(old, new):
    """Non-interactive rotation seam: NORM_OLD_PASSPHRASE + NORM_NEW_PASSPHRASE."""
    env = {}
    if old is not None:
        env["NORM_OLD_PASSPHRASE"] = old
    if new is not None:
        env["NORM_NEW_PASSPHRASE"] = new
    return env


# ── REQ-SEC-005: rotation re-wraps the key; old fails, new unlocks ────────────


def test_passwd_rotates_old_fails_new_unlocks(store):
    store.init()
    key_before = (store.data_dir / "key.json").read_bytes()

    result = store.run("passwd", passphrase=None, extra_env=_passwd_env(PASSPHRASE, NEW))
    assert result.returncode == 0, result.stderr
    assert "updated" in result.stdout.lower()

    # key.json was re-wrapped (fresh salt/nonce/ciphertext), still argon2id.
    key_after = (store.data_dir / "key.json").read_bytes()
    assert key_after != key_before
    assert json.loads(key_after.decode())["kdf"] == "argon2id"

    # old password no longer unlocks (exit 3); the new one does (exit 0).
    old_try = store.run("list", passphrase=PASSPHRASE)
    assert old_try.returncode == 3, old_try.stdout + old_try.stderr
    new_try = store.run("list", passphrase=NEW)
    assert new_try.returncode == 0, new_try.stderr


def test_passwd_wrong_old_password_is_auth_error_and_no_change(store):
    store.init()
    key_before = (store.data_dir / "key.json").read_bytes()

    result = store.run("passwd", passphrase=None, extra_env=_passwd_env("not the password", NEW))
    assert result.returncode == 3
    # nothing rotated: original password still unlocks, the would-be new one does not.
    assert (store.data_dir / "key.json").read_bytes() == key_before
    assert store.run("list", passphrase=PASSPHRASE).returncode == 0
    assert store.run("list", passphrase=NEW).returncode == 3


def test_passwd_uninitialized_store_is_not_found(store):
    result = store.run("passwd", passphrase=None, extra_env=_passwd_env(PASSPHRASE, NEW))
    assert result.returncode == 5
    assert not (store.data_dir / "key.json").exists()


def test_passwd_missing_new_password_non_interactive_fails_without_change(store):
    store.init()
    key_before = (store.data_dir / "key.json").read_bytes()
    # Only the old password available; no new one and no TTY → auth failure, no write.
    result = store.run("passwd", passphrase=None, extra_env=_passwd_env(PASSPHRASE, None))
    assert result.returncode == 3
    assert (store.data_dir / "key.json").read_bytes() == key_before
    assert store.run("list", passphrase=PASSPHRASE).returncode == 0


def test_passwd_key_file_has_no_plaintext_secrets_and_is_owner_only(store):
    store.init()
    rotated = store.run("passwd", passphrase=None, extra_env=_passwd_env(PASSPHRASE, NEW))
    assert rotated.returncode == 0, rotated.stderr

    key_path = store.data_dir / "key.json"
    text = key_path.read_text()
    assert PASSPHRASE not in text
    assert NEW not in text
    # owner-only, and no temp artifact left behind by the atomic write.
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert not (store.data_dir / "key.json.tmp").exists()


def test_passwd_json_error_envelope_on_wrong_old_password(store):
    store.init()
    result = store.run(
        "--json", "passwd", passphrase=None, extra_env=_passwd_env("wrong", NEW)
    )
    assert result.returncode == 3
    envelope = json.loads(result.stdout)
    assert envelope["error"]["code"] == "STORE_LOCKED"
    assert envelope["error"]["exit"] == 3
    assert envelope["error"]["message"]
