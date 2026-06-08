"""The in-process inference boundary (mlx-vlm), model provisioning, and its seams.

Inference runs **in-process** (REQ-ARCH-001): :func:`load_model` loads the weights
once, :func:`generate` runs the multimodal model per window — no server, socket, or
network. mlx-vlm is imported lazily so the heavy dependency is touched only on a real
run; ``record`` and ``report`` open zero network connections.

Model lifecycle (REQ-INIT-004): :func:`provision` is the *only* network step — it
downloads the weights into the local cache and is called solely by ``norm init``.
Before any load, :func:`ensure_available` verifies the weights are already cached
(reading only, no network) so ``report`` fails cleanly with MODEL_UNAVAILABLE (naming
``norm init``) instead of triggering a download. A malformed ``model_ref`` is caught
up front as INVALID_MODEL_REF, distinct from 'not downloaded' (PREPROCESS-005).

A prompt's provenance id (:func:`prompt_id`) is a sha256 prefix of its *effective*
text, persisted alongside each summary so a later run can tell which prompt produced a
row (PREPROCESS-001/003).

Hidden, test-only seams (never product features — norm-requirements
verification.test_seams):

* ``NORM_FAKE_MODEL=<trace>`` swaps load()/generate()/aggregate() for a spy that
  returns canned markdown and appends one JSON record per call —
  ``{model_ref, prompt, prompt_id, n_images, has_ax_text, n_summaries}`` — to the
  ``<trace>`` file. ``n_summaries`` is the window-summary count fed to an
  ``aggregate()`` (interval) call and ``0`` for a ``generate()`` (preprocess) call, so
  a test can tell the interval pass aggregated preprocess markdown rather than raw
  captures (INTERVAL-001). A bare truthy value (``1``/``true``) enables the spy
  without writing a trace. Under this seam the model is treated as present and
  loadable.
* ``NORM_FAKE_MODEL_CACHE=<dir>`` stands in for the Hugging Face cache:
  :func:`provision` drops a per-model marker there and :func:`ensure_available`
  checks for it, so the 'weights present / absent' branches are deterministic without
  the network or the multi-GB weights. It takes precedence over ``NORM_FAKE_MODEL``,
  so a test can force the 'weights absent' path even with the generate() spy enabled.

Together these remove the weights from the test path and make report tests fast,
deterministic, and assertable on the exact inputs that reached the model
(PREPROCESS-002, CONFIG-003/004).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from norm import errors

ENV_FAKE_MODEL = "NORM_FAKE_MODEL"
ENV_FAKE_MODEL_CACHE = "NORM_FAKE_MODEL_CACHE"
_PROMPT_ID_LEN = 12  # hex chars of the sha256 prefix kept as the prompt provenance id
_FLAG_TOKENS = {"1", "true", "yes", "on"}
_OFF_TOKENS = {"", "0", "false", "no", "off"}
# A Hugging Face repo id: one or two ``[A-Za-z0-9._-]`` segments (``name`` or
# ``org/name``), no whitespace, no ``..`` path traversal. Used to reject a malformed
# model_ref deterministically (INVALID_MODEL_REF) without touching the network.
_REPO_ID_RE = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?$")


def prompt_id(prompt_text: str) -> str:
    """Stable provenance id for a prompt: a sha256 hex prefix of its text (PREPROCESS-001)."""
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:_PROMPT_ID_LEN]


@dataclass
class Model:
    """An opaque handle to the loaded model — the real mlx-vlm backend, or the fake spy.

    ``backend`` is ``None`` under the ``NORM_FAKE_MODEL`` seam; otherwise it is the
    ``(model, processor)`` pair mlx-vlm's ``generate`` consumes.
    """

    model_ref: str
    backend: object | None


def load_model(model_ref: str) -> Model:
    """Load the model named by ``model_ref`` once, for reuse across windows.

    Availability is checked first (:func:`ensure_available`), so a missing/invalid
    model fails before any partial work — and never triggers a download. Under the
    fake seam the load itself is a no-op handle; on a real run it lazily loads the
    mlx-vlm weights and maps any import/load failure to a MODEL_ERROR (exit 4).
    """
    ensure_available(model_ref)
    if _fake_enabled():
        return Model(model_ref, None)
    return Model(model_ref, _load_backend(model_ref))


def generate(
    model: Model,
    *,
    prompt: str,
    images: list[Image.Image],
    ax_text: str,
    max_tokens: int = 512,
) -> str:
    """Run the model over a window's ``images`` + ``ax_text`` and return markdown.

    Both modalities and the prompt are passed through together (PREPROCESS-002).
    """
    if model.backend is None and _fake_enabled():
        return _fake_generate(model.model_ref, prompt, images, ax_text)
    return _real_generate(model, prompt, images, ax_text, max_tokens)


def aggregate(
    model: Model,
    *,
    prompt: str,
    summaries: list[str],
    max_tokens: int = 512,
) -> str:
    """Aggregate window-summary ``summaries`` (markdown) into one interval report.

    The interval pass consumes the preprocess markdown — not raw captures — so it
    passes text only, no images (INTERVAL-001, concept §10.11).
    """
    if model.backend is None and _fake_enabled():
        return _fake_aggregate(model.model_ref, prompt, summaries)
    return _real_aggregate(model, prompt, summaries, max_tokens)


# ── provisioning & availability ─────────────────────────────────────────────────


def provision(model_ref: str) -> str:
    """Download ``model_ref``'s weights into the local cache (the only network step).

    Called by ``norm init`` (unless ``--skip-model``); ``record`` / ``report`` never
    call this — they only ever *read* an already-provisioned cache (REQ-INIT-004,
    REQ-ARCH-001). Returns a short description of what was provisioned (for the
    ``init`` summary). A malformed ``model_ref`` is an INVALID_MODEL_REF (exit 4).
    """
    _require_repo_id(model_ref)
    fake_cache = _fake_cache_dir()
    if fake_cache is not None:
        return _fake_provision(fake_cache, model_ref)
    return _real_provision(model_ref)


def ensure_available(model_ref: str) -> None:
    """Verify ``model_ref``'s weights are locally present, without any network access.

    Raised *before* a load so ``report`` fails cleanly instead of downloading: a
    malformed ``model_ref`` → INVALID_MODEL_REF; a valid ref whose weights aren't
    cached → MODEL_UNAVAILABLE naming ``norm init`` (REQ-INIT-004, PREPROCESS-005).
    The shape check is deterministic and dependency-free, so the 'invalid ref' vs
    'not downloaded' distinction holds even offline.
    """
    _require_repo_id(model_ref)
    fake_cache = _fake_cache_dir()
    if fake_cache is not None:
        _fake_ensure(fake_cache, model_ref)
        return
    if _fake_enabled():
        return  # the NORM_FAKE_MODEL spy stands in for present, loadable weights
    _real_ensure(model_ref)


def _require_repo_id(model_ref: str) -> None:
    if not model_ref or ".." in model_ref or _REPO_ID_RE.match(model_ref) is None:
        raise errors.invalid_model_ref(
            f"invalid model ref {model_ref!r}: expected a Hugging Face id like 'org/name'"
        )


def _fake_cache_dir() -> Path | None:
    value = os.environ.get(ENV_FAKE_MODEL_CACHE)
    return Path(value) if value else None


def _fake_marker(cache_dir: Path, model_ref: str) -> Path:
    """The marker path for ``model_ref`` in the fake cache (HF's ``models--org--name``)."""
    return cache_dir / f"models--{model_ref.replace('/', '--')}"


def _fake_provision(cache_dir: Path, model_ref: str) -> str:
    marker = _fake_marker(cache_dir, model_ref)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(model_ref, encoding="utf-8")
    return f"{model_ref} (fake cache)"


def _fake_ensure(cache_dir: Path, model_ref: str) -> None:
    if not _fake_marker(cache_dir, model_ref).exists():
        raise errors.model_unavailable(
            f"model weights for {model_ref!r} are not downloaded; run `norm init`"
        )


def _real_provision(model_ref: str) -> str:
    """Download the real weights via huggingface_hub (lazily imported, like the backend)."""
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError as exc:
        raise errors.model_unavailable(
            "huggingface_hub is unavailable; cannot download the model weights"
        ) from exc
    snapshot_download(model_ref)
    return model_ref


def _real_ensure(model_ref: str) -> None:
    """Check the HF cache offline; any miss means the weights aren't provisioned yet."""
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError as exc:
        raise errors.model_unavailable(
            f"model weights for {model_ref!r} are not available; run `norm init`"
        ) from exc
    try:
        snapshot_download(model_ref, local_files_only=True)
    except Exception as exc:  # noqa: BLE001 — an offline cache miss == weights not provisioned
        raise errors.model_unavailable(
            f"model weights for {model_ref!r} are not downloaded; run `norm init`"
        ) from exc


# ── fake seam ─────────────────────────────────────────────────────────────────


def _fake_enabled() -> bool:
    value = os.environ.get(ENV_FAKE_MODEL)
    return value is not None and value.lower() not in _OFF_TOKENS


def _fake_trace_path() -> Path | None:
    value = os.environ.get(ENV_FAKE_MODEL)
    if value is None or value.lower() in _OFF_TOKENS or value.lower() in _FLAG_TOKENS:
        return None
    return Path(value)


def _fake_generate(model_ref: str, prompt: str, images: list[Image.Image], ax_text: str) -> str:
    """The spy for a preprocess call: record its inputs and return canned markdown."""
    _trace_call(model_ref, prompt, n_images=len(images), has_ax_text=bool(ax_text), n_summaries=0)
    return f"# Activity summary\n\n_(fake model output for prompt {prompt_id(prompt)})_\n"


def _fake_aggregate(model_ref: str, prompt: str, summaries: list[str]) -> str:
    """The spy for an interval call: record its inputs and return canned markdown."""
    _trace_call(
        model_ref, prompt, n_images=0,
        has_ax_text=bool("".join(summaries)), n_summaries=len(summaries),
    )
    return f"# Interval report\n\n_(fake aggregate output for prompt {prompt_id(prompt)})_\n"


def _trace_call(
    model_ref: str, prompt: str, *, n_images: int, has_ax_text: bool, n_summaries: int
) -> None:
    """Append one model-call record to the ``NORM_FAKE_MODEL`` trace (if a path is set)."""
    trace = _fake_trace_path()
    if trace is None:
        return
    record = {
        "model_ref": model_ref,
        "prompt": prompt,
        "prompt_id": prompt_id(prompt),
        "n_images": n_images,
        "has_ax_text": has_ax_text,
        "n_summaries": n_summaries,
    }
    with open(trace, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


# ── real mlx-vlm backend ────────────────────────────────────────────────────────


def _load_backend(model_ref: str):
    """Load the real mlx-vlm weights, mapping failures to a MODEL_ERROR (exit 4).

    Finalized alongside model provisioning (mirroring how capture defers the real
    macapptree binding); until then the ``NORM_FAKE_MODEL`` seam is the exercised path.
    """
    try:
        from mlx_vlm import load  # type: ignore
    except ImportError as exc:
        raise errors.model_unavailable(
            "mlx-vlm is not installed; run `norm init` to provision the model"
        ) from exc
    try:
        return load(model_ref)
    except Exception as exc:  # noqa: BLE001 — any load failure is a model error to the user
        raise errors.model_unavailable(
            f"could not load model {model_ref!r}; run `norm init` to download its weights"
        ) from exc


def _real_generate(model: Model, prompt: str, images, ax_text: str, max_tokens: int) -> str:
    from mlx_vlm import generate as mlx_generate  # type: ignore

    backend_model, processor = model.backend  # type: ignore[misc]
    full_prompt = f"{prompt}\n\nAccessibility context:\n{ax_text}"
    return mlx_generate(backend_model, processor, full_prompt, images, max_tokens=max_tokens)


def _real_aggregate(model: Model, prompt: str, summaries: list[str], max_tokens: int) -> str:
    from mlx_vlm import generate as mlx_generate  # type: ignore

    backend_model, processor = model.backend  # type: ignore[misc]
    joined = "\n\n---\n\n".join(summaries)
    full_prompt = f"{prompt}\n\nWindow summaries:\n{joined}"
    return mlx_generate(backend_model, processor, full_prompt, [], max_tokens=max_tokens)
