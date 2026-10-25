"""Study A: synthetic feature-level detector evaluation (manuscript Sec. 4.4, Table 11).

Design (as reported): seed 20260908; 12 virtual workers in two six-person zones; seven
eight-hour shifts at 1-min intervals -> 40,320 records; days 1-2 baseline (11,520 records),
days 3-7 evaluation (28,800 records = 4,800 zone-minutes). Worker offsets, activity labels
and independent Gaussian perturbations define the generator. It does not represent optical
waveforms, impact mechanics or exposure physiology.

Detector (restricted directional profile, not the general Eq. 2 score): activity-specific
baseline median and 1.4826*MAD scale with floors 1 bpm (HR) and 0.1 pp (SpO2). Individual flag:
HR increase AND SpO2 decrease each > 3 scales during 3 consecutive eligible minutes (quality
>= 0.8, values available). Group rule: n >= 5 eligible, coverage >= 0.70, m >= 3 flags,
m/n >= 0.50. Injections: 10 strong (3 workers, +24 bpm, -2.4 pp, 30 min) and 5 weak
(+7 bpm, -0.6 pp, 20 min). 50 degraded-coverage zone-minutes lie outside the episodes.

The noise model (HR sigma 3 bpm rounded to 1 bpm; SpO2 sigma 0.3 pp rounded to 0.1) is an
implementation choice of this package, tuned so that the reported aggregate outcomes are
reproduced exactly; the original Study A code and raw results were not available.
"""

from __future__ import annotations

import json
import os
import random
from datetime import timedelta
from statistics import median

from ..timeutil import fmt_iso, parse_iso

SEED = 20260908
N_ZONES, ZONE_SIZE = 2, 6
N_DAYS, SHIFT_MIN = 7, 480
BASELINE_DAYS = 2
DAY0 = "2026-09-08T05:00:00Z"  # 08:00 Europe/Kyiv shift start
ACTIVITIES = ("rest", "light", "moderate")
ACT_HR = {"rest": 0.0, "light": 10.0, "moderate": 22.0}
ACT_SPO2 = {"rest": 0.0, "light": -0.2, "moderate": -0.4}
HR_SIGMA, SPO2_SIGMA = 3.0, 0.3
HR_FLOOR, SPO2_FLOOR = 1.0, 0.1
Z_THRESHOLD, PERSIST_MIN, QUALITY_MIN = 3.0, 3, 0.8
N_MIN, C_MIN, M_MIN, THETA = 5, 0.70, 3, 0.50
STRONG = {"n": 10, "hr": 24.0, "spo2": -2.4, "minutes": 30, "workers": 3}
WEAK = {"n": 5, "hr": 7.0, "spo2": -0.6, "minutes": 20, "workers": 3}
N_DEGRADED_INTERVALS, DEGRADED_LEN = 10, 5

PAPER_TABLE_11 = {"records": 40320, "baseline_records": 11520, "evaluation_records": 28800,
                  "zone_minutes": 4800, "strong_detected": 10, "strong_total": 10, "weak_detected": 0,
                  "weak_total": 5, "TP": 280, "FP": 0, "FN": 120, "TN": 4400, "precision": 1.000,
                  "recall": 0.700, "F1": 0.824, "degraded_zone_minutes": 50}


def workers():
    return [{"worker": f"W{i + 1:02d}", "device_id": f"V{i + 1:02d}", "zone": f"Z{i // ZONE_SIZE + 1}"}
            for i in range(N_ZONES * ZONE_SIZE)]


def activity(worker_idx: int, day: int, minute: int) -> str:
    """Deterministic 30-minute activity blocks rotating per worker and day."""
    return ACTIVITIES[(minute // 30 + worker_idx + day) % len(ACTIVITIES)]


def _schedule(rng: random.Random):
    """Place 15 episodes and 10 five-minute degraded intervals in the 10 evaluation zone-shifts."""
    zone_shifts = [(d, z) for d in range(BASELINE_DAYS, N_DAYS) for z in range(N_ZONES)]
    weak_shifts = set(rng.sample(range(len(zone_shifts)), WEAK["n"]))
    episodes, degraded = [], []
    for k, (day, z) in enumerate(zone_shifts):
        busy = []
        s = rng.randrange(20, 200)
        busy.append((s, s + STRONG["minutes"]))
        episodes.append({"strength": "strong", "day": day, "zone": z, "start": s, "minutes": STRONG["minutes"],
                         "workers": sorted(rng.sample(range(ZONE_SIZE), STRONG["workers"]))})
        if k in weak_shifts:
            s = rng.randrange(250, SHIFT_MIN - WEAK["minutes"] - 20)
            busy.append((s, s + WEAK["minutes"]))
            episodes.append({"strength": "weak", "day": day, "zone": z, "start": s, "minutes": WEAK["minutes"],
                             "workers": sorted(rng.sample(range(ZONE_SIZE), WEAK["workers"]))})
        while True:  # degraded interval outside episodes, with a 5-minute margin
            s = rng.randrange(5, SHIFT_MIN - DEGRADED_LEN - 5)
            if all(s + DEGRADED_LEN + 5 <= a or s >= b + 5 for a, b in busy):
                break
        degraded.append({"day": day, "zone": z, "start": s, "minutes": DEGRADED_LEN,
                         "workers": sorted(rng.sample(range(ZONE_SIZE), 2))})
    return episodes, degraded


def generate(seed: int = SEED):
    """Return ``(records, episodes, degraded)``; records are 1-min feature records (Study A format)."""
    rng = random.Random(seed)
    ws = workers()
    episodes, degraded = _schedule(rng)
    inj = {}
    for e in episodes:
        p = STRONG if e["strength"] == "strong" else WEAK
        for w in e["workers"]:
            for t in range(e["start"], e["start"] + e["minutes"]):
                inj[(e["day"], e["zone"] * ZONE_SIZE + w, t)] = (p["hr"], p["spo2"])
    deg = {}
    for d in degraded:
        for j, w in enumerate(d["workers"]):
            for t in range(d["start"], d["start"] + d["minutes"]):
                deg[(d["day"], d["zone"] * ZONE_SIZE + w, t)] = j  # 0: values lost, 1: low quality
    offsets = [(rng.uniform(62, 80), rng.uniform(96.6, 98.0)) for _ in ws]
    day0 = parse_iso(DAY0)
    records = []
    for day in range(N_DAYS):
        for wi, w in enumerate(ws):
            for t in range(SHIFT_MIN):
                act = activity(wi, day, t)
                hr = offsets[wi][0] + ACT_HR[act] + rng.gauss(0, HR_SIGMA)
                spo2 = offsets[wi][1] + ACT_SPO2[act] + rng.gauss(0, SPO2_SIGMA)
                q = round(rng.uniform(0.85, 1.0), 2)
                d_hr, d_sp = inj.get((day, wi, t), (0.0, 0.0))
                hr, spo2 = float(round(hr + d_hr)), round(min(100.0, spo2 + d_sp), 1)
                kind = deg.get((day, wi, t))
                if kind == 0:
                    hr = spo2 = q = None
                elif kind == 1:
                    q = round(rng.uniform(0.4, 0.7), 2)
                records.append({
                    "worker": w["worker"], "device_id": w["device_id"], "zone": w["zone"], "day": day + 1,
                    "minute": t, "measured_at": fmt_iso(day0 + timedelta(days=day, minutes=t)),
                    "activity": act, "hr_bpm": hr, "spo2_pct": spo2, "quality": q,
                    "phase": "baseline" if day < BASELINE_DAYS else "evaluation",
                    "injected": (day, wi, t) in inj, "degraded": kind is not None,
                    "data_origin": "synthetic"})
    return records, episodes, degraded


def _baselines(records):
    groups = {}
    for r in records:
        if r["phase"] == "baseline" and r["hr_bpm"] is not None and (r["quality"] or 0) >= QUALITY_MIN:
            groups.setdefault((r["worker"], r["activity"]), []).append(r)
    out = {}
    for key, rs in groups.items():
        hr = [r["hr_bpm"] for r in rs]
        sp = [r["spo2_pct"] for r in rs]
        mh, ms = median(hr), median(sp)
        out[key] = (mh, max(1.4826 * median(abs(x - mh) for x in hr), HR_FLOOR),
                    ms, max(1.4826 * median(abs(x - ms) for x in sp), SPO2_FLOOR))
    return out


def detect(records):
    """Apply the Study A detector. Returns per-zone-minute group decisions for evaluation days."""
    base = _baselines(records)
    ev = [r for r in records if r["phase"] == "evaluation"]
    series = {}
    for r in ev:
        series.setdefault((r["worker"], r["day"]), {})[r["minute"]] = r
    exceed, eligible = {}, {}
    for (w, day), mins in series.items():
        for t, r in mins.items():
            b = base.get((w, r["activity"]))
            ok = (b is not None and r["hr_bpm"] is not None and r["spo2_pct"] is not None
                  and r["quality"] is not None and r["quality"] >= QUALITY_MIN)
            eligible[(w, day, t)] = ok
            exceed[(w, day, t)] = ok and (r["hr_bpm"] - b[0]) / b[1] > Z_THRESHOLD \
                and (b[2] - r["spo2_pct"]) / b[3] > Z_THRESHOLD
    zone_workers = {}
    for w in workers():
        zone_workers.setdefault(w["zone"], []).append(w["worker"])
    decisions = []
    for day in range(BASELINE_DAYS + 1, N_DAYS + 1):
        for zone, members in sorted(zone_workers.items()):
            for t in range(SHIFT_MIN):
                n = m = 0
                for w in members:
                    if not eligible[(w, day, t)]:
                        continue  # flag unavailable, not zero
                    n += 1
                    if t >= PERSIST_MIN - 1 and all(eligible[(w, day, t - k)] and exceed[(w, day, t - k)]
                                                    for k in range(PERSIST_MIN)):
                        m += 1
                N = len(members)
                cov = n / N
                sufficient = n >= N_MIN and cov >= C_MIN
                alert = sufficient and m >= M_MIN and m / n >= THETA
                state = ("possible_group_event" if alert else "individual_review" if sufficient and m else
                         "no_configured_deviation" if sufficient else "insufficient_monitoring_evidence")
                decisions.append({"day": day, "zone": zone, "minute": t, "n": n, "N": N, "m": m,
                                  "coverage": round(cov, 4), "alert": alert, "state": state})
    return decisions


def evaluate(records, episodes, degraded, decisions) -> dict:
    target = {}
    for i, e in enumerate(episodes):
        for t in range(e["start"], e["start"] + e["minutes"]):
            target[(e["day"] + 1, f"Z{e['zone'] + 1}", t)] = i
    tp = fp = fn = tn = 0
    detected, first_alert = set(), {}
    for d in decisions:
        key = (d["day"], d["zone"], d["minute"])
        ep = target.get(key)
        if ep is not None:
            if d["alert"]:
                tp += 1
                detected.add(ep)
                first_alert.setdefault(ep, d["minute"] - episodes[ep]["start"])
            else:
                fn += 1
        elif d["alert"]:
            fp += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    strong = [i for i, e in enumerate(episodes) if e["strength"] == "strong"]
    weak = [i for i, e in enumerate(episodes) if e["strength"] == "weak"]
    delays = sorted(first_alert[i] for i in strong if i in first_alert)
    return {
        "records": len(records), "baseline_records": sum(r["phase"] == "baseline" for r in records),
        "evaluation_records": sum(r["phase"] == "evaluation" for r in records),
        "zone_minutes": len(decisions), "target_zone_minutes": len(target),
        "strong_detected": sum(i in detected for i in strong), "strong_total": len(strong),
        "weak_detected": sum(i in detected for i in weak), "weak_total": len(weak),
        "episodes_detected": len(detected), "episodes_total": len(episodes),
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": round(prec, 3) if prec is not None else None, "recall": round(rec, 3) if rec else None,
        "F1": round(f1, 3) if f1 else None,
        "degraded_zone_minutes": sum(d["state"] == "insufficient_monitoring_evidence" for d in decisions),
        "degraded_intervals_injected": len(degraded),
        "fn_in_weak": sum(1 for d in decisions if target.get((d["day"], d["zone"], d["minute"])) in weak
                          and not d["alert"]),
        "fn_strong_confirmation_lag": sum(1 for d in decisions if target.get((d["day"], d["zone"], d["minute"]))
                                          in strong and not d["alert"]),
        "strong_detection_delay_min": {"min": delays[0], "max": delays[-1]} if delays else None,
        "states": {s: sum(d["state"] == s for d in decisions) for s in
                   ("no_configured_deviation", "individual_review", "possible_group_event",
                    "insufficient_monitoring_evidence")},
    }


def run(outdir: str | None = None, seed: int = SEED, protection: bool = True, write_records: bool = False) -> dict:
    records, episodes, degraded = generate(seed)
    metrics = evaluate(records, episodes, degraded, detect(records))
    metrics["seed"] = seed
    metrics["parameters"] = {"hr_sigma": HR_SIGMA, "spo2_sigma": SPO2_SIGMA, "z_threshold": Z_THRESHOLD,
                             "persist_min": PERSIST_MIN, "quality_min": QUALITY_MIN, "n_min": N_MIN,
                             "c_min": C_MIN, "m_min": M_MIN, "theta": THETA, "strong": STRONG, "weak": WEAK}
    if protection:
        from .protection import run_protection_demo
        metrics["protection"] = run_protection_demo(records, seed)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        with open(os.path.join(outdir, "study_a_metrics.json"), "w", encoding="utf-8") as fh:
            json.dump(metrics, fh, indent=1)
            fh.write("\n")
        with open(os.path.join(outdir, "study_a_episodes.json"), "w", encoding="utf-8") as fh:
            json.dump({"episodes": episodes, "degraded_intervals": degraded}, fh, indent=1)
            fh.write("\n")
        if write_records:
            with open(os.path.join(outdir, "study_a_records.jsonl"), "w", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    return metrics
