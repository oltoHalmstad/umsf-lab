"""Bench material: Stage-1 transcription (Table 13) and a Stage-2 scenario re-enactment (Table 6).

Stage 1 is a *transcription* of the thirteen visible application records (data_origin
``bench_transcription``). HR values are synthetic test values (``hr_synthetic: true``); the
temperature channel is not attributed to skin/core/ambient; PPG IR and motion keep the
interface's unspecified units. The node time of row 13 (122,488 ms) and gateway time 152,639 ms
are from the paper's example line; the other node/gateway millisecond values are reconstructed
as 10 s steps and the wall-clock date is a nominal placeholder (the bench had no common clock).

Stage 2 is a SYNTHETIC re-enactment of the documented scenario timeline for pipeline testing.
It is not the original data (none was logged). Background values follow Fig. 6 / Table 14.
Thresholds are implementation design choices, not calibrated limits. The local composite is
``possible_impact_local`` (unverified); nothing here attributes a strike.
"""

from __future__ import annotations

import csv
import json
import os
import random

from .. import frames
from ..records import event_record, station_record
from ..timeutil import from_epoch, to_epoch

# ----------------------------------------------------------------------------- Stage 1
TABLE_13 = {
    "seq": list(range(1, 14)),
    "time_s": list(range(2, 123, 10)),
    "temp_c": [21.81, 21.81, 21.88, 21.94, 21.94, 22.00, 22.00, 22.00, 22.06, 22.06, 22.13, 22.13, 22.19],
    "ppg_ir": [1224, 1222, 1216, 1207, 1204, 1203, 1201, 1193, 1192, 1189, 1186, 1181, 1187],
    "motion": [75, 99, 97, 100, 98, 97, 100, 102, 96, 99, 100, 98, 97],
    "hr_test": [71, 72, 73, 74, 75, 76, 70, 71, 72, 73, 74, 75, 76],
    "flags": ["TPM"] * 13,
}
PAPER_EXAMPLE_LINE = "RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPM"
NOMINAL_BOOT_EPOCH = "2026-01-01T00:00:00Z"  # placeholder; real wall-clock time unknown


def stage1_lines() -> list[str]:
    out = []
    for i, seq in enumerate(TABLE_13["seq"]):
        node_ms = 122488 - (13 - seq) * 10000
        gw_ms = 152639 - (13 - seq) * 10000
        out.append(f"RX,AG1,{gw_ms},F,A01,1,{seq},{node_ms},{round(TABLE_13['temp_c'][i] * 100)},"
                   f"{TABLE_13['ppg_ir'][i]},{TABLE_13['motion'][i]},{TABLE_13['hr_test'][i]},{TABLE_13['flags'][i]}")
    assert out[-1] == PAPER_EXAMPLE_LINE
    return out


def stage1_records() -> list[dict]:
    epoch = to_epoch(NOMINAL_BOOT_EPOCH)
    recs = []
    for line in stage1_lines():
        p = frames.parse_gateway_line(line)
        t = from_epoch(epoch + p["node_time_ms"] / 1000)
        rec = frames.line_to_record(p, site_id="BENCH-1", received_at=t, scenario_id="stage1-table13",
                                    data_origin="bench_transcription", hr_synthetic=True)
        rec["measured_at"] = t
        recs.append(rec)
    return recs


def stage1_stats() -> dict:
    t, temp, ppg, mot, seq = (TABLE_13[k] for k in ("time_s", "temp_c", "ppg_ir", "motion", "seq"))
    return {"records": len(seq), "sequence_continuous": seq == list(range(1, len(seq) + 1)),
            "duplicates": len(seq) - len(set(seq)), "span_s": t[-1] - t[0], "interval_s": sorted({b - a for a, b in zip(t, t[1:])}),
            "temp_start": temp[0], "temp_end": temp[-1], "temp_change": round(temp[-1] - temp[0], 2),
            "ppg_ir_range": [min(ppg), max(ppg)], "motion_range": [min(mot), max(mot)],
            "hr_test_range": [min(TABLE_13["hr_test"]), max(TABLE_13["hr_test"])],
            "flags": sorted(set(TABLE_13["flags"])),
            "note": "descriptive channel outputs; HR values are synthetic test values"}


# ----------------------------------------------------------------------------- Stage 2
TABLE_6 = [
    (1, 59, "background", "Overview and background state"),
    (59, 83, "manual_sos", "Activation, interface alarm, manual reset and operator event"),
    (83, 99, "mechanical_stimulus", "Impact on the assembly/support; impact and acoustic events"),
    (99, 123, "gas_sensitive_channel", "Lighter-related demonstration without reported ignition"),
    (123, 150, "orientation_change", "Manual inclination of the node (~63.3 deg)"),
    (150, 174, "loss_of_availability", "Power/communication loss (cause not independently measured)"),
    (174, 200, "motion_presence", "Infrared sensing; most recent presence indicators retained"),
]
BACKGROUND = {"vib_peak_g": 0.03, "tilt_deg": 0.4, "pressure_hpa": 1003.7, "temp_c": 21.9, "gas_v": 0.80,
              "sound_index": 262}
STAGE2_T0 = "2026-09-01T10:00:00Z"  # nominal synthetic start
SITE2, ZONE2, DEV2 = "BENCH-2", "workshop-1-north", "A01"
GAS_ALARM_V, TILT_ALARM_DEG, LOUD_INDEX, IMPACT_G = 1.20, 10.0, 2000, 1.5  # design choices
OUTAGE = (152, 171)  # no records in this interval (inclusive)


def phase_of(t: int) -> str:
    for a, b, name, _d in TABLE_6:
        if a <= t < b:
            return name
    return "after_sequence"


def stage2(seed: int = 2026) -> dict:
    rng = random.Random(seed)
    t0 = to_epoch(STAGE2_T0)
    station, events = [], []
    sos = False
    ev_n = 0

    def ev(t, etype, level, value, src="stationary_node", dev=DEV2, **kw):
        nonlocal ev_n
        ev_n += 1
        method = kw.pop("method", "synthetic re-enactment rule (design threshold, not calibrated)")
        events.append(event_record(
            site_id=SITE2, zone_id=ZONE2, event_id=f"{SITE2}-EV{ev_n:03d}", source_class=src, device_id=dev,
            event_type=etype, level=level, value=value, observed_at=from_epoch(t0 + t),
            reported_at=from_epoch(t0 + t + 0.3), time_uncertainty_s=0.5, rule_version=1,
            provenance={"source": f"{src}:{kw.get('gateway_id', dev)}", "method": method},
            data_origin="synthetic", scenario_id="stage2-reenactment", **kw))

    tilt_alarm = False
    for t in range(1, 200):
        v = {k: x for k, x in BACKGROUND.items()}
        v["vib_peak_g"] = round(0.03 + rng.uniform(-0.005, 0.005), 3)
        v["tilt_deg"] = round(0.4 + rng.uniform(-0.05, 0.05), 1)
        v["pressure_hpa"] = round(1003.7 + rng.uniform(-0.05, 0.05), 1)
        v["temp_c"] = round(21.9 + rng.uniform(-0.03, 0.03), 2)
        v["gas_v"] = round(0.80 + rng.uniform(-0.005, 0.005), 3)
        v["sound_index"] = int(262 + rng.uniform(-10, 10))
        pir = t < 59 or (t >= 174 and t % 20 < 12)
        if t == 62:
            sos = True
            ev(t, "sos", "urgent", 1.0, method="manual SOS button (GPIO27)")
        if t == 78:
            sos = False
            ev(t, "sos_reset", "notice", 1.0, method="manual operator reset")
        if t == 88:
            v["vib_peak_g"], v["sound_index"] = 3.2, 2900
            ev(t, "impact_excursion", "warning", 3.2)
            ev(t, "loud_sound", "warning", 2900.0)
            ev(t, "possible_impact_local", "warning", 3.2,
               method="local composite: impact + loud sound within 2 s; UNVERIFIED, not a strike attribution")
        if 99 <= t < 150:  # gas-sensitive channel: rise to 1.32 V, slow decay
            peak = 1.32
            g = 0.80 + (peak - 0.80) * min(1.0, (t - 99) / 12) if t < 115 else peak - (t - 115) * 0.012
            v["gas_v"] = round(max(0.80, g), 3)
            if v["gas_v"] >= GAS_ALARM_V and not any(e["event_type"] == "gas_channel_alarm" for e in events):
                ev(t, "gas_channel_alarm", "warning", v["gas_v"],
                   method="uncalibrated MQ-2 channel voltage above design threshold 1.20 V; no gas identity/concentration")
        tilt = 0.4
        if 125 <= t < 150:
            tilt = min(63.3, 0.4 + (t - 125) * 9.0) if t < 140 else 63.3
            v["tilt_deg"] = round(tilt, 1)
            if tilt - 0.4 >= TILT_ALARM_DEG and not tilt_alarm:
                tilt_alarm = True
            if tilt == 63.3 and not any(e["event_type"] == "tilt_change" for e in events):
                ev(t, "tilt_change", "warning", 62.9, method="inclination change vs. mounting reference")
        if t == 154:
            ev(t, "link_loss", "warning", 2.0, src="gateway", method="gateway AG1: no frame for 2 s (staleness)",
               gateway_id="AG1")
        if t == 172:
            ev(t, "link_restored", "notice", 20.0, src="gateway", method="gateway AG1: frames resumed",
               gateway_id="AG1")
        if t in (176, 196):
            ev(t, "presence", "info", 1.0 if t == 176 else 0.0, method="PIR state change (presence cue only)")
        if OUTAGE[0] <= t <= OUTAGE[1]:
            continue
        flags = (1 if pir else 0) | (2 if sos else 0) | (4 if t == 88 else 0) | (8 if t == 88 else 0) | \
            (16 if v["gas_v"] >= GAS_ALARM_V else 0) | (32 if tilt - 0.4 >= TILT_ALARM_DEG else 0) | \
            (128 if tilt_alarm else 0)
        station.append(station_record(
            site_id=SITE2, zone_id=ZONE2, device_id=DEV2, boot_id=1, sequence=t,
            measured_at=from_epoch(t0 + t), received_at=from_epoch(t0 + t + rng.uniform(0.05, 0.4)),
            data_origin="synthetic", scenario_id="stage2-reenactment", accel_rms_g=round(v["vib_peak_g"] / 3, 3),
            tilt_delta_deg=round(v["tilt_deg"] - 0.4, 1), pressure_delta_pa=int(rng.uniform(0, 4)),
            pir_presence=pir, sos=sos, quality=1.0, battery_pct=round(87.0 - t * 0.01, 1), flags=flags, sensor_flags=0x1F,
            fw_build=1, **v))
    return {"station": station, "events": events, "timeline": TABLE_6}


def station_to_frame(rec: dict, zone_code: int = 1) -> bytes:
    """Encode a station record as a STATION_STATE frame (exercise of the §2.3 encoder)."""
    def s(v, k):
        return None if v is None else round(v * k)
    payload = {"vib_peak_cg": s(rec["vib_peak_g"], 100), "accel_rms_mg": s(rec["accel_rms_g"], 1000),
               "tilt_ddeg": s(rec["tilt_deg"], 10), "tilt_delta_ddeg": s(rec["tilt_delta_deg"], 10),
               "pressure_dhpa": s(rec["pressure_hpa"], 10), "pressure_delta_pa": rec["pressure_delta_pa"],
               "temp": s(rec["temp_c"], 100), "gas_mv": s(rec["gas_v"], 1000), "gas_baseline_mv": 800,
               "sound_index": rec["sound_index"], "flags": rec.get("flags", 0),
               "quality_pct": s(rec["quality"], 100), "battery_pct": s(rec["battery_pct"], 1),
               "sensor_flags": rec.get("sensor_flags", 0), "n_imu_samples": 200, "window_ms": 1000,
               "zone_code": zone_code, "fw_build": rec.get("fw_build", 1)}
    hdr = {"source_class": 2, "device_id": rec["device_id"], "boot_id": rec["boot_id"],
           "sequence": rec["sequence"], "node_time_ms": rec["sequence"] * 1000}
    return frames.encode_frame(2, hdr, payload)


def _jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def write(outdir: str) -> dict:
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "stage1_table13.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["seq", "time_s", "temp_c", "ppg_ir", "motion", "hr_test_synthetic", "flags"])
        for i in range(13):
            w.writerow([TABLE_13[k][i] for k in ("seq", "time_s", "temp_c", "ppg_ir", "motion", "hr_test", "flags")])
    with open(os.path.join(outdir, "stage1_gateway_lines.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(stage1_lines()) + "\n")
    _jsonl(os.path.join(outdir, "stage1_records.jsonl"), stage1_records())
    stats = stage1_stats()
    s2 = stage2()
    _jsonl(os.path.join(outdir, "stage2_station.jsonl"), s2["station"])
    _jsonl(os.path.join(outdir, "stage2_events.jsonl"), s2["events"])
    with open(os.path.join(outdir, "stage2_station_frames.hex"), "w", encoding="utf-8") as fh:
        for r in s2["station"]:
            fh.write(f"{r['received_at']} {station_to_frame(r).hex()}\n")
    summary = {"stage1": stats, "stage2": {
        "label": "synthetic scenario re-enactment for pipeline testing; not original data",
        "station_records": len(s2["station"]), "events": {e["event_type"]: 0 for e in s2["events"]},
        "timeline": [{"from_s": a, "to_s": b, "phase": n, "description": d} for a, b, n, d in TABLE_6],
        "background": BACKGROUND, "outage_s": list(OUTAGE)}}
    for e in s2["events"]:
        summary["stage2"]["events"][e["event_type"]] += 1
    with open(os.path.join(outdir, "bench_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return summary
