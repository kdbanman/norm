"""``python -m tools.normdev`` — the developer CLI dispatch (``smoke`` / ``req``)."""

from __future__ import annotations

import argparse
import sys

from tools.normdev import concept
from tools.normdev import decisions as decs
from tools.normdev import requirements as reqs
from tools.normdev import run as run_mod
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

    p_run = sub.add_parser(
        "run", help="run an arbitrary norm command against an ephemeral store"
    )
    p_run.add_argument("--base", metavar="DIR", help="reuse/persist the store here (else a temp dir)")
    p_run.add_argument("--keep", action="store_true", help="keep a temp store after running")
    p_run.add_argument("--no-init", dest="no_init", action="store_true", help="don't auto-provision the store")
    p_run.add_argument("--capture", action="store_true", help="inject a fake capture frame (for record)")
    p_run.add_argument("--idle", type=int, default=0, metavar="SECONDS", help="fake idle seconds (with --capture)")
    p_run.add_argument("--locked", action="store_true", help="run with no passphrase (a locked store)")
    p_run.add_argument(
        "--env",
        action="append",
        metavar="KEY=VAL",
        help="extra env for the run (repeatable), e.g. --env NORM_OLD_PASSPHRASE=… for passwd",
    )
    p_run.add_argument(
        "argv",
        nargs=argparse.REMAINDER,
        metavar="-- norm args",
        help="the norm command to run (normdev flags must precede it), e.g. config set k v",
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

    p_dec = sub.add_parser("dec", help="query the decision records (ADRs)")
    dec_sub = p_dec.add_subparsers(dest="dec_command", required=True)
    dec_sub.add_parser("list", help="list every ADR (id, status, title)")
    p_dec_show = dec_sub.add_parser("show", help="show one ADR in full (untruncated)")
    p_dec_show.add_argument("id", help="ADR id, e.g. ADR-006 (or just 6)")

    return parser


def _parse_env(pairs: list[str] | None) -> dict[str, str] | None:
    """Turn repeated ``KEY=VAL`` ``--env`` flags into a dict (``None`` if none given).

    Raises ``ValueError`` on a malformed pair (no ``=`` or empty key) so the dispatch
    can report a usage error rather than silently dropping a seam.
    """
    if not pairs:
        return None
    env: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"--env expects KEY=VAL, got {pair!r}")
        env[key] = value
    return env


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
    for example in concept.for_requirement(req):
        print(f"concept  : {example.section} {example.title}")
        for line in example.body.splitlines():
            print(f"         | {line}")
    return 0


def _cmd_dec_list() -> int:
    rows = decs.load_decisions()
    for d in rows:
        print(f"  {d.id:<9} [{d.status or '?'}]  {d.title}")
    print(f"\n{len(rows)} decision record(s)")
    return 0


def _cmd_dec_show(adr_id: str) -> int:
    try:
        d = decs.find(adr_id)
    except KeyError:
        print(f"no such decision record: {adr_id}", file=sys.stderr)
        return 2
    print(f"{d.id} — {d.title}  [{d.status or '?'}]")
    print()
    print(d.body)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "smoke":
        return smoke_mod.main(keep=args.keep, base=args.base)
    if args.command == "run":
        try:
            env = _parse_env(args.env)
        except ValueError as exc:
            print(f"normdev run: {exc}", file=sys.stderr)
            return 2
        return run_mod.main(
            base=args.base,
            keep=args.keep,
            no_init=args.no_init,
            capture=args.capture,
            idle=args.idle,
            locked=args.locked,
            env=env,
            argv=args.argv,
        )
    if args.command == "req":
        if args.req_command == "list":
            return _cmd_req_list(args.category, args.outstanding)
        if args.req_command == "show":
            return _cmd_req_show(args.id)
    if args.command == "dec":
        if args.dec_command == "list":
            return _cmd_dec_list()
        if args.dec_command == "show":
            return _cmd_dec_show(args.id)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
