"""End-to-end smoke run: a throwaway store driven through the real ``norm`` CLI.

Stands up a fresh encrypted store under a temp dir, then drives ``init`` →
``record --once`` (store / dedupe / change / idle-skip) → ``status`` / ``list``
through the capture seams, checks the observable contract at each step, prints a
readable trace, and tears the store down again. This is the durable replacement
for the hand-typed ``rm -rf /tmp/normsmoke; init; record …`` smoke loop; it never
touches the real user's store and cleans up after itself.

Run: ``python -m tools.normdev smoke`` (``--keep`` to leave the store on disk).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from tools.normdev.harness import NormStore

_BASE_AX = {
    "role": "AXWindow",
    "title": "Editor",
    "children": [{"role": "AXButton", "title": "OK"}],
}


def _gradient(*, vertical: bool = False, size: int = 64) -> Image.Image:
    img = Image.new("L", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = (y if vertical else x) * 255 // size
    return img


def _write_frame(dir_path: Path, *, image: Image.Image, ax: dict, app: str) -> str:
    """Materialize one fake capture (image + AX + app name) for NORM_FAKE_CAPTURE."""
    dir_path.mkdir(parents=True, exist_ok=True)
    image.save(dir_path / "image.png")
    (dir_path / "ax.json").write_text(json.dumps(ax))
    (dir_path / "active_app.txt").write_text(app)
    return str(dir_path)


def _capture_env(frame_dir: str, *, idle: str = "0") -> dict[str, str]:
    return {"NORM_FAKE_CAPTURE": frame_dir, "NORM_FAKE_IDLE": idle}


@dataclass
class Smoke:
    """Accumulates pass/fail checks while walking the scripted flow."""

    checks: list[tuple[bool, str]] = field(default_factory=list)

    def check(self, ok: bool, label: str) -> None:
        self.checks.append((bool(ok), label))
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")

    @property
    def ok(self) -> bool:
        return all(ok for ok, _ in self.checks)


def _captures(store: NormStore) -> list[dict]:
    result = store.run("list", "--json")
    return store.json_out(result) if result.returncode == 0 else []


def run_smoke(base: Path, *, frames: Path) -> Smoke:
    """Drive the full flow against a store under ``base``; return the check log."""
    store = NormStore(base)
    s = Smoke()

    print("init")
    init = store.run("init", "--skip-model")
    s.check(init.returncode == 0, f"init exits 0 (got {init.returncode})")

    print("record a changed frame -> stored")
    a = _write_frame(frames / "a", image=_gradient(), ax=_BASE_AX, app="TextEdit")
    r = store.run("record", "--once", "--interval", "1", extra_env=_capture_env(a))
    s.check(r.returncode == 0, f"record exits 0 (got {r.returncode})")
    s.check(len(_captures(store)) == 1, "one capture stored")

    print("record the same frame again -> deduped")
    r = store.run("record", "--once", "--interval", "1", extra_env=_capture_env(a))
    s.check("duplicate" in (r.stdout + r.stderr).lower(), "reports duplicate")
    s.check(len(_captures(store)) == 1, "still one capture (no new row)")

    print("record a changed frame -> stored")
    b = _write_frame(frames / "b", image=_gradient(vertical=True), ax=_BASE_AX, app="Safari")
    store.run("record", "--once", "--interval", "1", extra_env=_capture_env(b))
    s.check(len(_captures(store)) == 2, "second capture stored")

    print("record while idle -> skipped")
    r = store.run(
        "record", "--once", "--idle-threshold", "1", extra_env=_capture_env(a, idle="600")
    )
    s.check("idle" in (r.stdout + r.stderr).lower(), "reports idle")
    s.check(len(_captures(store)) == 2, "nothing stored while idle")

    print("status / list")
    st = store.run("status")
    s.check(st.returncode == 0, f"status exits 0 (got {st.returncode})")
    rows = _captures(store)
    s.check(
        {row["active_app"] for row in rows} == {"TextEdit", "Safari"},
        "list shows both captured apps",
    )

    return s


def main(*, keep: bool, base: str | None) -> int:
    """Set up an ephemeral store, run the smoke flow, and clean up unless ``keep``."""
    created = base is None
    root = Path(base) if base else Path(tempfile.mkdtemp(prefix="norm-smoke-"))
    root.mkdir(parents=True, exist_ok=True)
    frames = root / "frames"
    print(f"smoke store: {root}\n")
    try:
        result = run_smoke(root, frames=frames)
    finally:
        if keep or not created:
            print(f"\nleaving store in place: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)

    passed = sum(1 for ok, _ in result.checks if ok)
    print(f"\n{passed}/{len(result.checks)} checks passed — {'OK' if result.ok else 'FAILED'}")
    return 0 if result.ok else 1
