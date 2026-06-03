# 17 — Verifying "no inference server / socket" (vs. allowed weight download)

- **Type:** Verification approach
- **Affects:** REQ-ARCH-001, REQ-PREPROCESS-002 ("no network socket to an inference server")

## The gap

"norm opens no listening socket for inference and connects to no model-server endpoint" is a
**negative network property**, not a CLI output. The subtlety: the **first** real model
`load()` legitimately downloads weights from `huggingface.co` (§5). So a naive "assert no
network" test gives **false failures** — we must distinguish *allowed weight egress* from a
*forbidden inference-server socket*.

## Options

- **(a) Pre-cache + zero-socket assertion** *(suspected)* — ensure weights are already in the
  HF cache (or use the fake model from [16]), then run `report` under a socket monitor
  (`lsof -nP -p <pid>` sampled, or `dtrace`/`fs_usage` on `listen()`/`connect()`); assert the
  process opens **no listening socket** and makes **no connection to a localhost inference
  port** (e.g. an `mlx_vlm.server`). With the fake model there should be **zero** sockets at
  all — the cleanest assertion.
- **(b) Network namespace / outbound block** — run with outbound network denied; if inference
  still succeeds from cache, it proves in-process. Distinguishes from a server that would
  need the socket.
- **(c) Process-tree check** — assert no child process/daemon is spawned for inference.

Recommendation: combine the **fake model [16]** (→ expect zero sockets) with a separate
real-weights "cached, offline" run (→ inference still works) to cover both the negative and
the positive form.

## Resolution

TODO
