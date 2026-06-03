# 18 — Verifying encryption at rest (without involving norm)

- **Type:** Verification approach
- **Affects:** REQ-SEC-001, plus the "blobs are ciphertext" clauses in REQ-RECORD-001 and REQ-PREPROCESS-001

## The gap

"All on-disk capture data is ciphertext" must be checked by inspecting files **directly, with
no norm involvement** — so it's an executable criterion, just not a `norm` CLI assertion.

## Options (all executable, non-CLI)

- **Magic-byte / parser negative tests** *(suspected core)* — for every blob under
  `data_dir/blobs/`: assert it does **not** start with the PNG/JPEG signature and **fails** to
  decode as an image; for AX blobs, assert it **fails** `json.loads`; for the index, assert it
  is **not** a readable SQLite db (no `SQLite format 3\0` header — SQLCipher encrypts the
  header too).
- **Entropy check** — assert blob byte-entropy is near-random (ciphertext), catching
  accidental plaintext that happens not to match a known magic number.
- **Round-trip control** — confirm `show --export` / `export` *can* recover valid PNG/JSON
  with the key, proving the at-rest files are the encrypted form of real data (not garbage).

Note: pair "no plaintext at rest" with the **transient-decryption** check during reporting in
[20]. These are setup/inspection helpers run around CLI calls, not assertions on norm's own
stdout.

## Resolution

TODO
