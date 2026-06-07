"""The in-process inference boundary (mlx-vlm) and its ``NORM_FAKE_MODEL`` seam.

Inference runs **in-process** (REQ-ARCH-001): :func:`load_model` loads the weights
once, :func:`generate` runs the multimodal model per window — no server, socket, or
network. mlx-vlm is imported lazily so the heavy dependency is touched only on a real
run; ``record`` and ``report`` open zero network connections (only ``init`` downloads
weights, INIT-004).

A prompt's provenance id (:func:`prompt_id`) is a sha256 prefix of its *effective*
text, persisted alongside each summary so a later run can tell which prompt produced a
row (PREPROCESS-001/003).

Hidden, test-only seam (never a product feature — norm-requirements
verification.test_seams): ``NORM_FAKE_MODEL=<trace>`` swaps load()/generate()/
aggregate() for a spy that returns canned markdown and appends one JSON record per
call — ``{model_ref, prompt, prompt_id, n_images, has_ax_text, n_summaries}`` — to
the ``<trace>`` file. ``n_summaries`` is the window-summary count fed to an
``aggregate()`` (interval) call and ``0`` for a ``generate()`` (preprocess) call, so
a test can tell the interval pass aggregated preprocess markdown rather than raw
captures (INTERVAL-001). This removes the multi-GB weights from the test path and
makes report tests fast, deterministic, and assertable on the exact inputs that
reached the model (PREPROCESS-002, CONFIG-003/004). A bare truthy value
(``1``/``true``) enables the spy without writing a trace.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from norm import errors

ENV_FAKE_MODEL = "NORM_FAKE_MODEL"
_PROMPT_ID_LEN = 12  # hex chars of the sha256 prefix kept as the prompt provenance id
_FLAG_TOKENS = {"1", "true", "yes", "on"}
_OFF_TOKENS = {"", "0", "false", "no", "off"}


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

    Under the fake seam this is a no-op handle. On a real run it lazily loads the
    mlx-vlm weights and maps any import/load failure to a MODEL_ERROR (exit 4).
    """
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
