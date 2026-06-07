"""Artifact-type vocabulary for the ``--include`` filter (``export`` / ``prune``).

The on-disk store holds three exportable/prunable kinds of plaintext-on-decrypt
data: capture screenshots (``images``), capture AX trees (``ax``), and the model's
markdown summaries (``reports`` — both preprocess windows and interval reports).
``export --include`` selects any subset of these; ``prune --include`` accepts only
``reports`` (it always targets captures). Centralizing the names + parsing keeps the
two commands' ``--include`` contract identical (REQ-DATA-005, REQ-DATA-006).
"""

from __future__ import annotations

from collections.abc import Iterable

from norm import errors

IMAGES = "images"
AX = "ax"
REPORTS = "reports"
ALL: tuple[str, ...] = (IMAGES, AX, REPORTS)


def parse_include(value: str | None, *, allowed: Iterable[str] = ALL) -> set[str]:
    """Parse a comma-separated ``--include`` value into a validated set of types.

    ``None`` (flag omitted) means "all ``allowed`` types". An unknown or empty type
    is a usage error (exit 2), raised before any store access so it outranks the
    auth/not-found checks (conventions.exit_precedence).
    """
    allowed = tuple(allowed)
    if value is None:
        return set(allowed)
    requested = [token.strip() for token in value.split(",") if token.strip()]
    if not requested:
        raise errors.usage_error("--include needs at least one artifact type")
    unknown = [token for token in requested if token not in allowed]
    if unknown:
        raise errors.usage_error(
            f"unknown --include type(s): {', '.join(unknown)}; "
            f"choose from {', '.join(allowed)}"
        )
    return set(requested)
