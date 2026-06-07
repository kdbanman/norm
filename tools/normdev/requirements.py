"""Read the requirements doc as data, for the "pick one outstanding requirement" step.

``planning_and_decisions/norm-requirements.html`` is a hand-authored, data-driven
page: it embeds the whole spec as a ``const DATA = {…}`` object that the page's JS
renders. That object — not the rendered markup — is the machine-readable source,
so this module extracts and parses it rather than scraping HTML tags. (The doc
stays hand-authored HTML by preference; we only *read* the embedded data.)

"Outstanding" is derived, since the doc carries no status field: a requirement is
considered covered once its id is referenced by a file under ``tests/`` (the RED
step writes failing acceptance criteria before any implementation), so the
outstanding set is exactly the requirements no test mentions yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tools.normdev import REPO_ROOT

DEFAULT_DOC = REPO_ROOT / "planning_and_decisions" / "norm-requirements.html"
TESTS_DIR = REPO_ROOT / "tests"
SRC_DIR = REPO_ROOT / "src"


@dataclass(frozen=True)
class Requirement:
    id: str
    category: str
    title: str
    command: str | None
    preconditions: list[str]
    pass_if: list[str]
    fail_if: list[str]


def _extract_data_object(html: str) -> dict:
    """Pull the ``const DATA = {…}`` object out of the requirements page.

    Brace-balances from the first ``{`` after the assignment, respecting string
    literals, so a ``}`` inside a quoted value never ends the object early.
    """
    marker = html.find("const DATA")
    if marker == -1:
        raise ValueError("requirements doc has no `const DATA` block")
    start = html.find("{", marker)
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start : i + 1])
    raise ValueError("unbalanced braces in `const DATA` block")


def load_requirements(doc: Path = DEFAULT_DOC) -> list[Requirement]:
    """Parse every requirement from the doc, in document order."""
    data = _extract_data_object(Path(doc).read_text())
    return [
        Requirement(
            id=r["id"],
            category=r["category"],
            title=r["title"],
            command=r.get("command"),
            preconditions=list(r.get("preconditions", [])),
            pass_if=list(r.get("pass_if", [])),
            fail_if=list(r.get("fail_if", [])),
        )
        for r in data["requirements"]
    ]


def find(req_id: str, doc: Path = DEFAULT_DOC) -> Requirement:
    """Look up one requirement by id (case-insensitive), or raise ``KeyError``."""
    want = req_id.upper()
    for req in load_requirements(doc):
        if req.id.upper() == want:
            return req
    raise KeyError(req_id)


def references(req_id: str, root: Path) -> list[Path]:
    """Files under ``root`` whose text mentions ``req_id`` (sorted, repo-relative).

    Matches either the full id (``REQ-RECORD-001``) or its short form
    (``RECORD-001``) — tests and docstrings cite requirements both ways.
    """
    forms = (req_id, req_id.removeprefix("REQ-"))
    root = Path(root)
    hits: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if any(form in text for form in forms):
            # Report repo-relative when under the repo, else relative to root.
            base = REPO_ROOT if path.is_relative_to(REPO_ROOT) else root
            hits.append(path.relative_to(base))
    return hits


def is_covered(req_id: str, tests_dir: Path = TESTS_DIR) -> bool:
    """True once some test references ``req_id`` (the RED step has been written)."""
    return bool(references(req_id, tests_dir))
