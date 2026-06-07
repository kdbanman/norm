"""Read the concept doc's §10 worked examples, to cross-link them from ``req show``.

``planning_and_decisions/norm-concept.html`` ends with a set of ``$ norm …`` worked
examples (``<div class="worked-example">`` blocks). They are the companion to the
requirements doc's pass/fail criteria — the "what does a run look like" half of the
spec to read before the RED step. This module parses those blocks so the dev CLI can
print the example(s) matching a requirement, instead of the maintainer hand-slicing
HTML.

A worked example is matched to a requirement by *subcommand*: the first non-flag
token after ``norm`` in the requirement's command (e.g. ``config``) against the same
token in the example's transcript. The doc stays hand-authored HTML by preference;
we only read it.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from tools.normdev import REPO_ROOT

DEFAULT_DOC = REPO_ROOT / "planning_and_decisions" / "norm-concept.html"

_BLOCK_RE = re.compile(r'<div class="worked-example"[^>]*>(.*?)</div>', re.DOTALL)
_H3_RE = re.compile(r"<h3>(.*?)</h3>", re.DOTALL)
_PRE_RE = re.compile(r'<pre class="example">(.*?)</pre>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class WorkedExample:
    section: str  # e.g. "§10.17"
    title: str  # e.g. "config set / get"
    body: str  # the transcript text ($ norm … / before / after / …)
    subcommands: frozenset[str]  # norm subcommands the transcript invokes


def subcommands_in(text: str) -> set[str]:
    """The norm subcommands invoked in ``text`` — the first non-flag token per call.

    Handles both transcript lines (``$ norm config set …``) and requirement command
    strings (``norm config get x ; norm config path``). Only a leading ``norm`` token
    counts, so prose mentioning ``~/.norm/…`` is never read as an invocation.
    """
    found: set[str] = set()
    for fragment in re.split(r"[;\n]", text):
        line = fragment.strip().lstrip("$").strip()
        if line != "norm" and not line.startswith("norm "):
            continue
        for token in line[len("norm") :].split():
            if not token.startswith("-"):
                found.add(token)
                break
    return found


def load_worked_examples(doc: Path = DEFAULT_DOC) -> list[WorkedExample]:
    """Parse every ``<div class="worked-example">`` block, in document order."""
    text = Path(doc).read_text()
    examples: list[WorkedExample] = []
    for block in _BLOCK_RE.findall(text):
        heading_m = _H3_RE.search(block)
        body_m = _PRE_RE.search(block)
        if not (heading_m and body_m):
            continue
        heading = html.unescape(_TAG_RE.sub("", heading_m.group(1))).strip()
        body = html.unescape(body_m.group(1)).strip()
        section, _, title = heading.partition(" ")
        examples.append(
            WorkedExample(
                section=section,
                title=title.strip(),
                body=body,
                subcommands=frozenset(subcommands_in(body)),
            )
        )
    return examples


def for_command(name: str, doc: Path = DEFAULT_DOC) -> list[WorkedExample]:
    """Worked examples whose transcript invokes the ``name`` subcommand."""
    return [ex for ex in load_worked_examples(doc) if name in ex.subcommands]


def for_requirement(req, doc: Path = DEFAULT_DOC) -> list[WorkedExample]:
    """Worked examples sharing a subcommand with ``req``'s command string."""
    wanted = subcommands_in(req.command or "")
    if not wanted:
        return []
    return [ex for ex in load_worked_examples(doc) if ex.subcommands & wanted]
