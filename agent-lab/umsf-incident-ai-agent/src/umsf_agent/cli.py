"""Command-line interface: `umsf-agent`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import __version__
from .util import dumps, parse_ts


def _agent(args, **kw):
    from .agent import Agent
    return Agent(args.data, args.out, policy_path=getattr(args, "policy", None), use_llm=getattr(args, "llm", False),
                 auto_approve=getattr(args, "auto_approve_for_simulation", False),
                 interactive=getattr(args, "interactive", False), **kw)


def _print_summary(res, out_dir, auto):
    resc, cont = res["rescue"], res["continuity"]["result"]
    print(f"state at {res['as_of']} (data origin: {res['data_origin']})")
    print(f"  open assistance requests: {sum(len(p['assistance_requests']) for p in resc['personnel'])}; "
          f"assignments: {len(resc['assignments'])}; unassigned urgent: {len(resc['unassigned_urgent'])}")
    print(f"  continuity: {cont['status']}" + (f", Q = {cont['Q_pct']:.2f}%" if cont["Q_pct"] is not None else ""))
    print(f"  recovery: {sum(1 for t in res['recovery']['tasks'] if t['status'] == 'scheduled_candidate')} scheduled, "
          f"{len(res['recovery']['blocked'])} blocked")
    print(f"outputs: {os.path.abspath(out_dir)}")
    if auto:
        print("WARNING: --auto-approve-for-simulation was used; approvals are SIMULATED, not human decisions.")
    else:
        print("All packages are PROPOSALS awaiting authorisation. Use:\n"
              f"  umsf-agent approve --out {out_dir} --package <ID> --role <ROLE> --by <NAME> --reason <TEXT>\n"
              f"  umsf-agent reject  --out {out_dir} --package <ID> --role <ROLE> --by <NAME> --reason <TEXT>")


def cmd_run(args) -> int:
    a = _agent(args)
    res = a.run(parse_ts(args.as_of) if args.as_of else None)
    _print_summary(res, args.out, args.auto_approve_for_simulation)
    return 0


def cmd_replay(args) -> int:
    a = _agent(args)
    res = a.replay(parse_ts(args.start) if args.start else None, parse_ts(args.end) if args.end else None, args.step)
    changes = sum(1 for r in a.timeline if r["changed_domains"])
    print(f"replayed {len(a.timeline)} steps of {args.step} s; re-proposals at {changes} steps")
    _print_summary(res, args.out, args.auto_approve_for_simulation)
    return 0


def cmd_authorise(args, decision: str) -> int:
    from .agent import record_authorisation
    from .audit import AuditLog
    path = os.path.join(args.out, "decision_packages.json")
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    pk = next((p for p in doc["packages"] if p["package_id"] == args.package), None)
    if pk is None:
        print(f"package {args.package} not found among current packages in {path}", file=sys.stderr)
        return 2
    audit = AuditLog(os.path.join(args.out, "audit.jsonl"))
    try:
        e = record_authorisation(audit, pk, decision, args.role, args.by, args.reason, pk.get("scenario_time"))
    except ValueError as exc:
        print(f"not recorded: {exc}", file=sys.stderr)
        return 3
    pk["authorisation"] = {"decision": decision, "role": args.role, "actor": args.by, "reason": args.reason,
                           "seq": e["seq"], "recorded_at": e["recorded_at"]}
    pk["status"] = decision
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(doc) + "\n")
    # re-render the deterministic briefing, report and dashboard with the recorded decision
    res_path = os.path.join(args.out, "result.json")
    if os.path.exists(res_path):
        from .report import write_reports
        with open(res_path, "r", encoding="utf-8") as fh:
            res = json.load(fh)
        tl_path = os.path.join(args.out, "timeline.json")
        tl = []
        if os.path.exists(tl_path):
            with open(tl_path, "r", encoding="utf-8") as fh:
                tl = json.load(fh)
        write_reports(args.out, res, doc["packages"], tl, None, auto_approve=doc.get("auto_approve_for_simulation", False))
    print(f"{decision}: {args.package} by {args.by} ({args.role}); audit seq {e['seq']}")
    return 0


def cmd_demo(args) -> int:
    from .scenario import generate
    from .agent import Agent
    inp = os.path.join(args.out, "input")
    run = os.path.join(args.out, "run")
    generate(inp, seed=args.seed)
    print(f"SYNTHETIC scenario written to {inp}")
    a = Agent(inp, run, use_llm=args.llm, auto_approve=args.auto_approve_for_simulation)
    res = a.replay(step_s=args.step)
    print(f"replayed {len(a.timeline)} steps; re-proposals at {sum(1 for r in a.timeline if r['changed_domains'])} steps")
    _print_summary(res, run, args.auto_approve_for_simulation)
    return 0


def cmd_reproduce(args) -> int:
    from .paper import checks, format_report
    from .continuity import fig14_table
    rows = checks()
    print(format_report(rows))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(dumps({"checks": rows, "fig14": fig14_table()}) + "\n")
    return 0 if all(r["pass"] for r in rows) else 1


def cmd_verify(args) -> int:
    from .audit import verify_chain
    ok, problems = verify_chain(args.audit)
    print("audit chain OK" if ok else "audit chain BROKEN:\n  " + "\n  ".join(problems))
    return 0 if ok else 1


def cmd_generate(args) -> int:
    from .scenario import generate
    p = generate(args.out, seed=args.seed, variant=args.variant)
    print("SYNTHETIC scenario files:\n  " + "\n  ".join(sorted(p.values())))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="umsf-agent", description=(
        "Evidence-aware AI decision-support agent: rescue logistics and consequence-liquidation logistics. "
        "Deterministic planning; every plan is a proposal requiring human authorisation."))
    ap.add_argument("--version", action="version", version=f"umsf-agent {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, data=True):
        if data:
            p.add_argument("--data", required=True, help="dataset directory (roster.json, physio.jsonl, ...)")
        p.add_argument("--out", required=True, help="output directory")
        p.add_argument("--policy", help="command policy JSON overriding defaults")
        p.add_argument("--llm", action="store_true", help="add an optional Claude-written briefing (falls back offline)")
        p.add_argument("--auto-approve-for-simulation", action="store_true",
                       help="SIMULATION ONLY: mark proposals as approved by a simulated actor (never a human decision)")

    p = sub.add_parser("run", help="assess and plan at one time point (default: end of data)")
    common(p)
    p.add_argument("--as-of", help="ISO-8601 UTC time of the state to evaluate")
    p.add_argument("--interactive", action="store_true", help="prompt for approve/reject per package")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("replay", help="time-stepped replay with change detection and re-planning")
    common(p)
    p.add_argument("--step", type=int, default=60, help="scenario seconds per step (default 60)")
    p.add_argument("--start")
    p.add_argument("--end")
    p.set_defaults(func=cmd_replay)

    for name, dec in (("approve", "approved"), ("reject", "rejected")):
        p = sub.add_parser(name, help=f"record a human {dec} decision with reason in the audit log")
        p.add_argument("--out", required=True, help="output directory of a run/replay")
        p.add_argument("--package", required=True)
        p.add_argument("--role", required=True, help="authorising role (Table 9)")
        p.add_argument("--by", required=True, help="identity of the person deciding")
        p.add_argument("--reason", required=True)
        p.set_defaults(func=lambda a, d=dec: cmd_authorise(a, d))

    p = sub.add_parser("demo", help="generate the synthetic scenario and run end-to-end offline")
    p.add_argument("--out", default="demo_out")
    p.add_argument("--seed", type=int, default=20261014)
    p.add_argument("--step", type=int, default=60)
    p.add_argument("--llm", action="store_true")
    p.add_argument("--auto-approve-for-simulation", action="store_true")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("reproduce-paper", help="check Table 10 and Section 4.9 results; nonzero exit on mismatch")
    p.add_argument("--json", help="also write checks and Fig. 14 data as JSON")
    p.set_defaults(func=cmd_reproduce)

    p = sub.add_parser("verify-audit", help="verify the hash chain of an audit log")
    p.add_argument("--audit", required=True)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("generate-scenario", help="write the synthetic scenario input directory")
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=20261014)
    p.add_argument("--variant", default="post_impact", choices=["post_impact", "no_backup_power"])
    p.set_defaults(func=cmd_generate)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
