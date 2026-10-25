"""Command-line interface: ``umsf-dataset <subcommand>`` (or ``python -m umsf_dataset``)."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__


def load_rosters(path: str) -> dict:
    """Accept a single roster, a facility wrapper ``{"sites": [...]}``, or a ``{site_id: roster}`` map."""
    with open(path, encoding="utf-8") as fh:
        obj = json.load(fh)
    if "zones" in obj:
        return {obj["site_id"]: obj}
    if "sites" in obj:
        return {r["site_id"]: r for r in obj["sites"]}
    return obj


def _open_inputs(paths):
    for p in paths:
        if p == "-":
            yield "-", sys.stdin
        else:
            with open(p, encoding="utf-8") as fh:
                yield p, fh


def cmd_synth_study_a(a):
    from .synth import study_a
    m = study_a.run(a.out, seed=a.seed, protection=not a.no_protection, write_records=a.write_records)
    print(json.dumps({k: m[k] for k in ("records", "strong_detected", "weak_detected", "TP", "FP", "FN", "TN",
                                        "precision", "recall", "F1", "degraded_zone_minutes")}, indent=1))
    return 0


def cmd_synth_study_b(a):
    from .synth import study_b
    g = study_b.write(a.out, seed=a.seed)
    print(json.dumps({k: v for k, v in g["truth"].items() if not k.endswith("identities")}, indent=1))
    return 0


def cmd_synth_bench(a):
    from .synth import bench
    s = bench.write(a.out)
    print(json.dumps(s["stage1"], indent=1))
    return 0


def cmd_synth_incident(a):
    from .synth import incident
    m = incident.write(a.out, seed=a.seed, duration_s=int(a.duration_min * 60), station_interval_s=a.station_interval)
    print(json.dumps(m["counts"], indent=1))
    return 0


def cmd_ingest(a):
    from .store import Store
    from .timeutil import to_epoch
    st = Store(a.db)
    total = {}
    conv = {}
    if a.boot_epoch:
        conv["boot_epoch"] = to_epoch(a.boot_epoch)
    for name, fh in _open_inputs(a.inputs):
        if a.format == "jsonl":
            res = st.ingest_jsonl(fh, source=name, allow_measured=a.allow_measured)
        elif a.format == "gateway-lines":
            res = st.ingest_gateway_lines(fh, site_id=a.site, received_at=a.received_at, source=name,
                                          data_origin=a.origin, **conv)
        else:
            res = st.ingest_frames_hex(fh, site_id=a.site, source=name, data_origin=a.origin, **conv)
        for k, v in res.items():
            total[k] = total.get(k, 0) + v
    print(json.dumps({"ingest": total, "store": st.stats()}, indent=1))
    st.close()
    return 0


def cmd_summarize(a):
    from .store import Store
    from .summaries import physio_window_summaries
    st = Store(a.db)
    s = physio_window_summaries(st.records("physio"), load_rosters(a.roster), cutoff_at=a.cutoff)
    text = json.dumps(s, indent=1, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    st.close()
    return 0


def cmd_export(a):
    from .export import export_all
    from .store import Store
    from .summaries import physio_window_summaries
    st = Store(a.db)
    summ = physio_window_summaries(st.records("physio"), load_rosters(a.roster)) if a.roster else None
    m = export_all(st, a.out, summaries=summ, sources=a.source or [], generated_at=a.generated_at)
    print(json.dumps({"exports": len(m["exports"]), "counters": m["counters"]}, indent=1))
    st.close()
    return 0


def cmd_selfcheck(a):
    import tempfile
    from .synth import study_b
    r = study_b.run(a.workdir or tempfile.mkdtemp(prefix="umsf-selfcheck-"))
    for c in r["checks"]:
        print(f"[{'PASS' if c['passed'] else 'FAIL'}] {c['name']}: {c['detail']}")
    print(f"{r['selfchecks_passed']} passed, {r['selfchecks_failed']} failed")
    return 0 if r["selfchecks_failed"] == 0 else 1


def cmd_reproduce(a):
    from .reproduce import format_table, run
    r = run(a.workdir, protection=not a.no_protection)
    if a.json:
        print(json.dumps(r["rows"], indent=1))
    else:
        print(format_table(r["rows"]))
        print(f"\nResult: {'ALL MATCH' if r['ok'] else 'MISMATCH'} (workdir: {r['workdir']})")
    return 0 if r["ok"] else 1


def cmd_validate(a):
    from .validate import validate_line
    bad = 0
    n = 0
    for name, fh in _open_inputs(a.inputs):
        for i, line in enumerate(fh, 1):
            if not line.strip():
                continue
            n += 1
            _k, _o, errs = validate_line(line, allow_measured=a.allow_measured)
            if errs:
                bad += 1
                print(f"{name}:{i}: {'; '.join(errs)}")
    print(f"{n} lines, {n - bad} valid, {bad} invalid")
    return 0 if bad == 0 else 1


def cmd_vectors(a):
    from .frames import load_test_vectors
    rep = load_test_vectors(a.path)
    for f in rep["failed"]:
        print(f"FAIL {f['name']}: {'; '.join(f['errors'])}")
    print(f"{rep['passed']}/{rep['total']} vectors passed")
    return 0 if not rep["failed"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="umsf-dataset", description="UMSF incident dataset toolkit (research software)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synth-study-a", help="Study A synthetic detector evaluation (Table 11)")
    s.add_argument("--out", required=True)
    s.add_argument("--seed", type=int, default=20260908)
    s.add_argument("--no-protection", action="store_true", help="skip the Ed25519/AES-GCM demo")
    s.add_argument("--write-records", action="store_true", help="also write the 40,320 records (JSONL)")
    s.set_defaults(func=cmd_synth_study_a)

    s = sub.add_parser("synth-study-b", help="Study B challenge stream (Table 12 input)")
    s.add_argument("--out", required=True)
    s.add_argument("--seed", type=int, default=82026)
    s.set_defaults(func=cmd_synth_study_b)

    s = sub.add_parser("synth-bench", help="Stage-1 transcription + Stage-2 scenario re-enactment")
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_synth_bench)

    s = sub.add_parser("synth-incident", help="synthetic post-impact incident dataset for P3")
    s.add_argument("--out", required=True)
    s.add_argument("--seed", type=int, default=20261014)
    s.add_argument("--duration-min", type=float, default=30)
    s.add_argument("--station-interval", type=int, default=1)
    s.set_defaults(func=cmd_synth_incident)

    s = sub.add_parser("ingest", help="ingest JSONL, gateway text lines or frame hex into SQLite")
    s.add_argument("--db", required=True)
    s.add_argument("--format", choices=("jsonl", "gateway-lines", "frames-hex"), default="jsonl")
    s.add_argument("--site", default="SITE-LOCAL", help="site_id for gateway-lines / frames-hex")
    s.add_argument("--origin", default="synthetic_payload_physical_transport", help="data_origin for converted input")
    s.add_argument("--received-at", help="fixed received_at for gateway lines (default: now)")
    s.add_argument("--boot-epoch", help="qualified wall-clock time of node_time_ms = 0 (ISO, Z)")
    s.add_argument("--allow-measured", action="store_true")
    s.add_argument("inputs", nargs="+", help="files or - for stdin")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("summarize", help="roster-based five-minute summaries")
    s.add_argument("--db", required=True)
    s.add_argument("--roster", required=True)
    s.add_argument("--cutoff", help="fixed report cutoff (ISO, Z) for partial reports")
    s.add_argument("--out")
    s.set_defaults(func=cmd_summarize)

    s = sub.add_parser("export", help="daily CSV/JSONL, summaries, quarantine log and manifest")
    s.add_argument("--db", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--roster")
    s.add_argument("--source", nargs="*")
    s.add_argument("--generated-at")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("selfcheck", help="run the ten Study B functional self-checks")
    s.add_argument("--workdir")
    s.set_defaults(func=cmd_selfcheck)

    s = sub.add_parser("reproduce", help="reproduce Study A + B + bench and compare with the paper")
    s.add_argument("--workdir")
    s.add_argument("--no-protection", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_reproduce)

    s = sub.add_parser("validate", help="validate JSONL records against the schemas")
    s.add_argument("--allow-measured", action="store_true")
    s.add_argument("inputs", nargs="+")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("vectors", help="check a binary frame test-vector file")
    s.add_argument("path")
    s.set_defaults(func=cmd_vectors)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
