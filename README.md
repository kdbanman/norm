# norm

`norm` is a local, privacy-first activity recorder for **macOS (Apple Silicon)**. On a
timed loop it captures a screenshot plus the active window's accessibility (AX) tree,
stores both **encrypted on disk**, and runs a **local** multimodal model (Gemma 4 via
`mlx-vlm`, in-process) over your capture history to write markdown summaries of what you
were doing.

Nothing leaves your machine. The only command that touches the network is `norm init`
(to download the model weights once); `record` and `report` make zero network
connections.

## Requirements

- macOS on Apple Silicon. Runs unsandboxed, never elevated (no `sudo`), no Keychain.
- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).
- **Screen Recording** and **Accessibility** permission, granted to your terminal (or to
  `norm`) under *System Settings → Privacy & Security*. Without them, capture exits 6.

## Install

```sh
uv sync                      # create the venv and install norm (editable) + deps
uv run norm --help
```

For a `norm` on your `PATH`, install the project as a tool:

```sh
uv tool install .            # then just: norm --help
```

## Quickstart

```sh
# 1. Create the encrypted store and download the model weights (one-time, online).
#    You'll be prompted for an app password that protects the data key.
norm init

# 2. Record. Captures every 5 minutes; skips when idle or the screen hasn't changed.
#    Runs in the foreground until Ctrl-C; or use `--once` for a single frame.
norm record

# 3. Summarize the last day's activity as markdown.
norm report interval --last 24h --auto-preprocess
```

`record` and `report` need the store unlocked. Provide the app password by interactive
prompt, the `NORM_PASSPHRASE` environment variable, or a `chmod 400` password file under
`~/.norm/` (which lets the recorder run unattended).

## Commands

| Command | What it does |
|---|---|
| `norm init` | Create the encrypted store and provision the model. `--skip-model` to defer the download; `--force` to re-initialize (destroys existing data). |
| `norm record` | Capture on a timed loop. `--once` for a single frame; `--interval`, `--idle-threshold`, `--phash-threshold` to tune the gate. |
| `norm report preprocess` | Summarize sliding windows of captures (`--window`, `--stride`). |
| `norm report interval` | Aggregate window summaries over a range into one markdown report. `--auto-preprocess` fills gaps first; `--output` writes to a file. |
| `norm status` | Show store and daemon state. |
| `norm list` | List captures in a time range (`--from`/`--to`, or `--last 24h`). |
| `norm show <id>` | Show one capture's metadata; `--export DIR` to decrypt its artifacts. |
| `norm export` | Decrypt a range of artifacts to a directory (`--out`, `--include`). |
| `norm prune` | Delete captures before a cutoff (`--before`, `--dry-run`). |
| `norm config` | `get` / `set` a value, or print the config file `path`. |
| `norm passwd` | Rotate the app password. |

Global flags: `--config PATH`, `--data-dir PATH`, `--json` (machine-readable output and a
stable `{"error":{...}}` envelope), `-v`/`-q`. Run any command with `--help` for details.

## How it works

- **Capture gate.** Each tick skips when you're idle (HID idle ≥ `idle_threshold_seconds`)
  and deduplicates frames whose screenshot perceptual-hash and AX tree both match the
  previous capture — duplicates extend the prior capture's duration instead of storing a
  new one. On multi-monitor setups the display holding the active window is captured, so
  the screenshot and AX tree always describe the same window.
- **Reporting.** `report preprocess` runs the model over sliding windows of captures to
  produce per-window summaries; `report interval` aggregates those summaries across a time
  range into a single markdown report. Inference is in-process via `mlx-vlm` — no server,
  socket, or daemon.

## Configuration

`norm config get|set <key>` reads and writes `~/.norm/config.toml`; `--config PATH` or
`--data-dir PATH` override per-invocation. Keys and defaults:

| Key | Default | Meaning |
|---|---|---|
| `interval_minutes` | `5` | Minutes between captures. |
| `idle_threshold_seconds` | `300` | Idle seconds above which a tick is skipped. |
| `phash_threshold` | `4` | Max screenshot phash distance still treated as unchanged. |
| `data_dir` | `~/Library/Application Support/norm` | Where the encrypted store lives. |
| `model` | `mlx-community/gemma-4-e4b-it-4bit` | MLX model ref for inference. |
| `window_k` | `6` | Captures per preprocess window. |
| `stride_j` | `3` | Captures a window advances each step. |
| `max_tokens` | `512` | Max new tokens generated per summary. |
| `prompt_preprocess` / `prompt_interval` | built-in | Prompts for each stage. |

## Security & privacy

- **Encrypted at rest.** Screenshots, AX trees, the index, and reports are stored as
  AES-256-GCM ciphertext. Plaintext is written only when you explicitly ask for it via
  `--export`/`--output`.
- **App password.** Your password wraps the data key with Argon2id (like an SSH private
  key); the wrapped key lives on disk, the password never does.
- **Local only.** Only `init` reaches the network. `record` and `report` are fully
  offline and run entirely in-process.

## Environment variables

- `NORM_PASSPHRASE` — app password for unlocking the store non-interactively.
- `NORM_OLD_PASSPHRASE` / `NORM_NEW_PASSPHRASE` — non-interactive `passwd` rotation.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Unexpected runtime failure |
| 2 | Usage error (unknown command, bad argument) |
| 3 | Auth error (store locked, wrong/missing password) |
| 4 | Model error (weights missing, bad ref, inference failure) |
| 5 | Not found (no captures/coverage, unknown id, not initialized) |
| 6 | Environment error (missing macOS permission, capture backend unavailable) |

## Development

```sh
uv sync
uv run pytest                # narrow with: uv run pytest tests/test_x.py::name
uv run norm <args>
```

Planning docs are the source of truth (`planning_and_decisions/`): the concept,
requirements, and decision records. The dev CLI under `tools/normdev` wraps the recurring
chores — `make smoke`, `make req`/`make req-todo`, `make dec` — see `CLAUDE.md`.

## License

MIT.
