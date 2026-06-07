"""``python -m tools.normdev`` — the developer CLI dispatch (``smoke`` / ``req``)."""

from __future__ import annotations

import argparse
import sys

from tools.normdev import requirements as reqs
from tools.normdev import smoke as smoke_mod


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.normdev",
        description="norm developer tooling (not part of the shipped CLI).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_smoke = sub.add_parser(
        "smoke", help="drive the real CLI end-to-end against a throwaway store"
    )
    p_smoke.add_argument(
        "--keep", action="store_true", help="leave the smoke store on disk afterwards"
    )
    p_smoke.add_argument(
        "--base", metavar="DIR", help="use DIR as the store root (implies --keep semantics)"
    )

    p_req = sub.add_parser("req", help="query the requirements doc")
    req_sub = p_req.add_subparsers(dest="req_command", required=True)

    p_list = req_sub.add_parser("list", help="list requirements (✓ = referenced by a test)")
    p_list.add_argument("--category", help="only this category (e.g. record, security)")
    p_list.add_argument(
        "--outstanding", action="store_true", help="only requirements no test references yet"
    )

    p_show = req_sub.add_parser("show", help="show one requirement in full")
    p_show.add_argument("id", help="requirement id, e.g. REQ-RECORD-005")

    return parser


def _cmd_req_list(category: str | None, outstanding: bool) -> int:
    rows = reqs.load_requirements()
    shown = 0
    for req in rows:
        if category and req.category != category:
            continue
        covered = reqs.is_covered(req.id)
        if outstanding and covered:
            continue
        print(f"  {'✓' if covered else '·'}  {req.id:<18} {req.category:<16} {req.title}")
        shown += 1
    suffix = " outstanding" if outstanding else ""
    print(f"\n{shown}{suffix} requirement(s)")
    return 0


def _cmd_req_show(req_id: str) -> int:
    try:
        req = reqs.find(req_id)
    except KeyError:
        print(f"no such requirement: {req_id}", file=sys.stderr)
        return 2
    covered = reqs.is_covered(req.id)
    print(f"{req.id} — {req.title}  [{req.category}]")
    print(f"coverage : {'covered by a test' if covered else 'OUTSTANDING (no test references it)'}")
    if req.command:
        print(f"command  : {req.command}")
    for name, items in (
        ("precond ", req.preconditions),
        ("pass_if ", req.pass_if),
        ("fail_if ", req.fail_if),
    ):
        for i, item in enumerate(items):
            print(f"{name if i == 0 else '        '} : {item}")
    refs = reqs.references(req.id, reqs.TESTS_DIR) + reqs.references(req.id, reqs.SRC_DIR)
    if refs:
        print("referenced in:")
        for path in refs:
            print(f"  {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "smoke":
        return smoke_mod.main(keep=args.keep, base=args.base)
    if args.command == "req":
        if args.req_command == "list":
            return _cmd_req_list(args.category, args.outstanding)
        if args.req_command == "show":
            return _cmd_req_show(args.id)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
