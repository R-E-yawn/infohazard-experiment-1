"""`python -m exp1.review <command>`."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, paths


def _cmd_serve(args) -> int:
    from . import server
    server.serve(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def _cmd_selfcheck(args) -> int:
    from . import conditions
    result = conditions.build()
    ck = result["checks"]
    print(f"Layer 1 conditions self-check: {ck['status'].upper()} "
          f"({ck['passed']}/{ck['total']})")
    print()
    for c in ck["checks"]:
        mark = "  ok  " if c["ok"] else ("FAIL  " if c.get("critical") else "WARN  ")
        print(f"{mark} {c['title']}")
        if not c["ok"] or args.verbose:
            print(f"         {c['detail']}")
    print()
    for c in result["conditions"]:
        d = c.get("diff_vs_c3")
        print(f"  {c['condition']:22s} plants={str(c['plants_file']):5s} "
              f"words={c['memo_words']:4d} sentinel={str(c['sentinel_present']):5s} "
              f"section={c['variable_heading'] or '-'}"
              + (f"  (vs C3: {d['stats']['changed_lines']} lines differ)"
                 if d else ""))
    if args.json:
        print()
        print(json.dumps(ck, indent=2))
    return 0 if ck["status"] != "fail" else 1


def _cmd_report(args) -> int:
    from . import records, reports, store
    eps = records.load_all()
    ver = store.load()
    written = reports.write_all(eps, ver)
    print(f"{len(eps)} episodes, "
          f"{len(ver.get('verdicts') or {})} verdicts")
    for k, v in written.items():
        print(f"  {k}: {v}")
    return 0


def _cmd_synth(args) -> int:
    from . import make_synthetic
    return make_synthetic.main(
        (["--clean"] if args.clean else []) + ["--seed", str(args.seed)])


def _cmd_validate(args) -> int:
    """Load every record, print contract problems and invariant violations.
    Exit non-zero if anything is wrong -- usable as a pre-flight gate."""
    from . import aggregate, records, store
    eps = records.load_all()
    ver = store.load()
    bad = 0
    print(f"{len(eps)} episode records loaded from "
          f"{paths.rel(paths.EPISODES_DIR)}/")
    print()
    for e in eps:
        d = e["_derived"]
        if d["problems"] or d["invariants"]:
            bad += 1
            print(f"  {e.get('episode_id')}")
            for p in d["problems"]:
                print(f"    contract: {p}")
            for i in d["invariants"]:
                print(f"    !! {i}")
    if not bad:
        print("  no contract problems, no invariant violations")
    print()
    q = aggregate.review_queue(eps, ver)
    print(f"mandatory review: {len(q['mandatory'])}, "
          f"outstanding: {len(q['outstanding'])}")
    t = aggregate.build_table(eps, ver)
    print(f"coverage: {t['coverage']}")
    return 1 if bad else 0


def _cmd_selftest(args) -> int:
    from . import _selftest
    return _selftest.main()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m exp1.review",
        description="exp1 ground-truth review app. Three layers: conditions "
                    "(pre-run), results table (auto vs verified), episode page "
                    "(evidence first, labels last). Blind mode is on by default.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
root: {paths.ROOT}

keyboard, in the episode view:
  j / k      next / previous episode          1-6   set label
  a          agree with all automated labels  n     focus the note
  b          toggle blind mode                ?     help
  enter      submit the verdict

outputs:
  {paths.rel(paths.VERIFICATION)}
  {paths.rel(paths.AGREEMENT_REPORT)}
  {paths.rel(paths.RESULTS_REPORT)}

Set EXP1_ROOT to point the app at a different copy of the tree.
""")
    ap.add_argument("--version", action="version",
                    version=f"exp1.review {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="start the review app on localhost")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8731)
    p.add_argument("--no-browser", action="store_true",
                   help="do not open a browser window")
    p.set_defaults(func=_cmd_serve)

    p = sub.add_parser("selfcheck",
                       help="Layer 1 condition assertions, in the terminal")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_selfcheck)

    p = sub.add_parser("validate",
                       help="check every episode record against the contract")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("report",
                       help="write agreement_report.md and results.md")
    p.set_defaults(func=_cmd_report)

    p = sub.add_parser("synth", help="write synthetic episode records")
    p.add_argument("--clean", action="store_true")
    p.add_argument("--seed", type=int, default=20260101)
    p.set_defaults(func=_cmd_synth)

    p = sub.add_parser("selftest", help="run the built-in assertions")
    p.set_defaults(func=_cmd_selftest)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)
