"""Read the decision records (``norm-decisions.html``) as data, so the dev CLI can
print an ADR in full instead of agents hand-scraping the HTML.

The recurring hack this replaces was a heredoc that crudely stripped tags and kept
``[:4000]`` characters — which loses structure, leaves HTML entities raw, and
silently drops the tail (the *newest*, usually most-relevant records). The whole
doc is only ~2.5k tokens cleaned, so there is nothing to truncate.

Each decision is a ``<section id="adr-NNN">`` with an ``<h2>`` heading and a
``<div class="resolution …">`` whose trailing class token carries the status
(e.g. ``resolved``). The doc stays hand-authored HTML by preference; we only read
it — same posture as :mod:`tools.normdev.concept` and
:mod:`tools.normdev.requirements`.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from tools.normdev import REPO_ROOT

DEFAULT_DOC = REPO_ROOT / "planning_and_decisions" / "norm-decisions.html"

_SECTION_RE = re.compile(
    r'<section id="(adr-\d+)"[^>]*>(.*?)</section>', re.DOTALL | re.IGNORECASE
)
_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.DOTALL)
_RESOLUTION_RE = re.compile(r'<div class="resolution([^"]*)"')
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_END_RE = re.compile(r"</(p|div|h[1-6]|li|ul|ol)>", re.IGNORECASE)


@dataclass(frozen=True)
class Decision:
    id: str  # "ADR-001"
    title: str  # heading minus the "ADR-001 — " prefix
    status: str  # trailing class of the resolution div, e.g. "resolved" ("" if none)
    body: str  # full text after the heading: tags stripped, entities decoded, untruncated


def _to_text(fragment: str) -> str:
    """Render an HTML fragment to readable plain text.

    Block-closing tags become line breaks (so paragraphs stay separated), then
    tags are removed and entities decoded — in that order, so ``&lt;args&gt;`` in
    a code sample survives as ``<args>`` rather than being eaten as a tag.
    """
    text = _BLOCK_END_RE.sub("\n", fragment)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):  # collapse runs of blank lines to one
            out.append(ln)
    return "\n".join(out).strip()


def _parse_section(attr_id: str, inner: str) -> Decision:
    adr_id = attr_id.upper()  # adr-001 -> ADR-001
    h2 = _H2_RE.search(inner)
    heading = html.unescape(_TAG_RE.sub("", h2.group(1))).strip() if h2 else adr_id
    _, _, title = heading.partition("—")  # "ADR-001 — Title" -> "Title"
    res = _RESOLUTION_RE.search(inner)
    status = (res.group(1).split() or [""])[-1] if res else ""
    body = _to_text(inner[h2.end() :] if h2 else inner)
    return Decision(id=adr_id, title=(title or heading).strip(), status=status, body=body)


def load_decisions(doc: Path = DEFAULT_DOC) -> list[Decision]:
    """Parse every ``<section id="adr-NNN">`` block, in document order."""
    text = Path(doc).read_text()
    return [_parse_section(attr_id, inner) for attr_id, inner in _SECTION_RE.findall(text)]


def _normalize(adr_id: str) -> str:
    """Accept ``ADR-006`` / ``adr-6`` / ``6`` -> canonical ``ADR-006``."""
    m = re.fullmatch(r"(?:ADR-?)?0*(\d+)", adr_id.strip(), re.IGNORECASE)
    return f"ADR-{int(m.group(1)):03d}" if m else adr_id.strip().upper()


def find(adr_id: str, doc: Path = DEFAULT_DOC) -> Decision:
    """Look up one ADR by id (lenient on case / prefix / zero-padding), or raise ``KeyError``."""
    want = _normalize(adr_id)
    for d in load_decisions(doc):
        if d.id == want:
            return d
    raise KeyError(adr_id)
