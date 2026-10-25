"""Binary frame codec, fragment reassembly and gateway text-line parser (PROTOCOL.md §2-§3).

Decoded frame format (stable; used for cross-project test vectors)::

    {"header": {"magic", "version", "source_class", "frame_type", "device_id",
                "boot_id", "sequence", "node_time_ms"},
     "payload": {<spec field names, raw integer scaled values, null sentinel -> None>},
     "crc_ok": bool}

COMPACT packets decode to the same shape with header ``{"magic", "node_index", "seq"}``.
Bit-field bytes (``channel_flags``, ``artifact_flags``, ``flags``, ``sensor_flags``) and
control fields (event_type, level, related_seq_lo, ACK/CONFIG fields) are never null.
CRC-16 detects corruption only; it is not authentication.
"""

from __future__ import annotations

import json
import struct
import time
from typing import Callable, Optional

from . import SCHEMA_EVENT, SCHEMA_PHYSIO, SCHEMA_STATION

MAGIC = 0xB5
COMPACT_MAGIC = 0xC5
VERSION = 1
HEADER_FMT = "<BBBB4sHII"
HEADER_LEN = struct.calcsize(HEADER_FMT)  # 18
FRAG_HDR_FMT = "<HBB"
FRAG_HDR_LEN = 4
MAX_REASSEMBLY = 512
FRAGMENT_TIMEOUT_S = 2.0
COMPACT_LEN = 20

SOURCE_CLASSES = {1: "personnel_node", 2: "stationary_node", 3: "gateway"}
FRAME_TYPES = {1: "PHYSIO_FEATURE", 2: "STATION_STATE", 3: "EVENT", 4: "STATUS", 5: "ACK", 6: "CONFIG"}
EVENT_TYPES = {
    1: ("sos", "1"), 2: ("sos_reset", "1"), 3: ("impact_excursion", "g"), 4: ("loud_sound", "index"),
    5: ("gas_channel_alarm", "V"), 6: ("tilt_change", "deg"), 7: ("pressure_transient", "Pa"),
    8: ("presence", "1/0"), 9: ("link_loss", "s"), 10: ("possible_impact_local", "g"),
    11: ("help_request", "1"), 12: ("link_restored", "s"), 13: ("buffer_eviction", "count"),
}
EVENT_CODES = {name: code for code, (name, _u) in EVENT_TYPES.items()}
LEVELS = {0: "info", 1: "notice", 2: "warning", 3: "urgent"}

# (field, struct code, nullable)
_PAYLOADS = {
    1: [("skin_temp", "h", True), ("hr", "H", True), ("spo2", "H", True), ("ppg_ir_mean", "I", True),
        ("ppg_red_mean_div16", "H", True), ("ppg_valid_permille", "H", True), ("motion_rms_mg", "H", True),
        ("gsr_mv", "H", True), ("quality_pct", "B", True), ("battery_pct", "B", True),
        ("channel_flags", "B", False), ("artifact_flags", "B", False), ("n_ppg_samples", "H", True),
        ("n_imu_samples", "H", True), ("window_ms", "H", True), ("fw_build", "H", True)],
    2: [("vib_peak_cg", "H", True), ("accel_rms_mg", "H", True), ("tilt_ddeg", "h", True),
        ("tilt_delta_ddeg", "h", True), ("pressure_dhpa", "H", True), ("pressure_delta_pa", "h", True),
        ("temp", "h", True), ("gas_mv", "H", True), ("gas_baseline_mv", "H", True), ("sound_index", "H", True),
        ("flags", "B", False), ("quality_pct", "B", True), ("battery_pct", "B", True), ("sensor_flags", "B", False),
        ("n_imu_samples", "H", True), ("window_ms", "H", True), ("zone_code", "H", True), ("fw_build", "H", True)],
    3: [("event_type", "B", False), ("level", "B", False), ("value", "i", True), ("rule_version", "H", True),
        ("zone_code", "H", True), ("related_seq_lo", "H", False)],
    4: [("battery_pct", "B", True), ("buffered_records", "B", True), ("evicted_total", "H", True),
        ("sent_total", "I", True), ("acked_up_to_seq", "I", True), ("fw_build", "H", True),
        ("sensor_flags", "B", False), ("rssi_neg", "B", True)],
    5: [("target_boot_id", "H", False), ("reserved", "H", False), ("ack_up_to_seq", "I", False)],
    6: [("zone_code", "H", False), ("feature_window_ms", "H", False), ("sample_profile", "B", False),
        ("synthetic_hr_enabled", "B", False), ("reserved", "H", False)],
}
_COMPACT_FIELDS = [("vib_peak_cg", "H", True), ("tilt_ddeg", "h", True), ("pressure_dhpa", "H", True),
                   ("temp", "h", True), ("gas_mv", "H", True), ("sound_index", "H", True),
                   ("flags", "B", False), ("battery_pct", "B", True)]
SENTINELS = {"B": 0xFF, "H": 0xFFFF, "I": 0xFFFFFFFF, "h": -32768, "i": -(2 ** 31)}
PAYLOAD_LEN = {ft: struct.calcsize("<" + "".join(f[1] for f in fl)) for ft, fl in _PAYLOADS.items()}


class FrameError(ValueError):
    """Raised for structurally invalid frames (length, magic, version, type)."""


def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, xorout 0."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _unpack_fields(fields, raw: bytes) -> dict:
    values = struct.unpack("<" + "".join(f[1] for f in fields), raw)
    out = {}
    for (name, code, nullable), v in zip(fields, values):
        out[name] = None if nullable and v == SENTINELS[code] else v
    return out


def _pack_fields(fields, values: dict) -> bytes:
    vals = []
    for name, code, nullable in fields:
        v = values.get(name)
        if v is None:
            if not nullable and name not in ("reserved", "related_seq_lo"):
                raise FrameError(f"field {name} may not be null")
            v = SENTINELS[code] if nullable else 0
        vals.append(int(v))
    return struct.pack("<" + "".join(f[1] for f in fields), *vals)


def encode_frame(frame_type: int, header: dict, payload: dict) -> bytes:
    """Encode a framed record. ``header`` needs source_class, device_id, boot_id, sequence, node_time_ms."""
    if frame_type not in _PAYLOADS:
        raise FrameError(f"unknown frame_type {frame_type}")
    dev = header["device_id"].encode("ascii")
    if len(dev) > 4:
        raise FrameError("device_id longer than 4 ASCII bytes")
    hdr = struct.pack(HEADER_FMT, header.get("magic", MAGIC), header.get("version", VERSION),
                      header["source_class"], frame_type, dev.ljust(4, b"\0"), header["boot_id"],
                      header["sequence"], header["node_time_ms"])
    body = hdr + _pack_fields(_PAYLOADS[frame_type], payload)
    return body + struct.pack("<H", crc16_ccitt_false(body))


def decode_frame(data: bytes) -> dict:
    """Decode one complete frame. Raises FrameError on structural errors; CRC is reported, not raised."""
    data = bytes(data)
    if len(data) < HEADER_LEN + 2:
        raise FrameError(f"frame too short ({len(data)} bytes)")
    magic, version, sc, ft, dev, boot, seq, node_ms = struct.unpack_from(HEADER_FMT, data)
    if magic != MAGIC:
        raise FrameError(f"bad magic 0x{magic:02X}")
    if version != VERSION:
        raise FrameError(f"unsupported version {version}")
    if ft not in _PAYLOADS:
        raise FrameError(f"unknown frame_type {ft}")
    expected = HEADER_LEN + PAYLOAD_LEN[ft] + 2
    if len(data) != expected:
        raise FrameError(f"length {len(data)} != {expected} for frame_type {ft}")
    (crc,) = struct.unpack_from("<H", data, expected - 2)
    header = {"magic": magic, "version": version, "source_class": sc, "frame_type": ft,
              "device_id": dev.rstrip(b"\0").decode("ascii", "replace"), "boot_id": boot,
              "sequence": seq, "node_time_ms": node_ms}
    payload = _unpack_fields(_PAYLOADS[ft], data[HEADER_LEN:expected - 2])
    return {"header": header, "payload": payload, "crc_ok": crc == crc16_ccitt_false(data[:expected - 2])}


def encode_compact(node_index: int, seq: int, values: dict) -> bytes:
    body = struct.pack("<BBH", COMPACT_MAGIC, node_index, seq & 0xFFFF) + _pack_fields(_COMPACT_FIELDS, values)
    return body + struct.pack("<H", crc16_ccitt_false(body))


def decode_compact(data: bytes) -> dict:
    data = bytes(data)
    if len(data) != COMPACT_LEN:
        raise FrameError(f"compact packet must be 20 bytes, got {len(data)}")
    magic, node_index, seq = struct.unpack_from("<BBH", data)
    if magic != COMPACT_MAGIC:
        raise FrameError(f"bad compact magic 0x{magic:02X}")
    (crc,) = struct.unpack_from("<H", data, 18)
    return {"header": {"magic": magic, "node_index": node_index, "seq": seq},
            "payload": _unpack_fields(_COMPACT_FIELDS, data[4:18]),
            "crc_ok": crc == crc16_ccitt_false(data[:18])}


def decode_any(data: bytes) -> dict:
    """Decode a full frame (magic 0xB5) or a COMPACT packet (magic 0xC5, 20 bytes)."""
    if data and data[0] == COMPACT_MAGIC and len(data) == COMPACT_LEN:
        return decode_compact(data)
    return decode_frame(data)


# --------------------------------------------------------------------------- fragmentation
def fragment(frame: bytes, att_payload: int = 244, msg_id: int = 0) -> list[bytes]:
    """Split a frame into notifications, each carrying the 4-byte fragment header."""
    chunk = att_payload - FRAG_HDR_LEN
    if chunk <= 0:
        raise ValueError("ATT payload too small for fragment header")
    if len(frame) > MAX_REASSEMBLY:
        raise FrameError("frame exceeds 512-byte reassembly limit")
    parts = [frame[i:i + chunk] for i in range(0, len(frame), chunk)] or [b""]
    if len(parts) > 255:
        raise FrameError("too many fragments")
    return [struct.pack(FRAG_HDR_FMT, msg_id & 0xFFFF, i, len(parts)) + p for i, p in enumerate(parts)]


class Reassembler:
    """Bounded fragment reassembly: 512-byte limit, 2 s incomplete-message timeout."""

    def __init__(self, limit: int = MAX_REASSEMBLY, timeout_s: float = FRAGMENT_TIMEOUT_S,
                 clock: Callable[[], float] = time.monotonic):
        self.limit, self.timeout_s, self.clock = limit, timeout_s, clock
        self._pending: dict = {}
        self.stats = {"completed": 0, "timeouts": 0, "oversize": 0, "malformed": 0}

    def expire(self, now: Optional[float] = None) -> int:
        now = self.clock() if now is None else now
        old = [k for k, v in self._pending.items() if now - v["t0"] > self.timeout_s]
        for k in old:
            del self._pending[k]
        self.stats["timeouts"] += len(old)
        return len(old)

    def feed(self, data: bytes, source: str = "", now: Optional[float] = None) -> Optional[bytes]:
        """Feed one notification; returns the complete frame when the last fragment arrives."""
        now = self.clock() if now is None else now
        self.expire(now)
        if len(data) < FRAG_HDR_LEN:
            self.stats["malformed"] += 1
            return None
        msg_id, idx, count = struct.unpack_from(FRAG_HDR_FMT, data)
        chunk = bytes(data[FRAG_HDR_LEN:])
        if count == 0 or idx >= count:
            self.stats["malformed"] += 1
            return None
        if count == 1:
            if len(chunk) > self.limit:
                self.stats["oversize"] += 1
                return None
            self.stats["completed"] += 1
            return chunk
        key = (source, msg_id)
        st = self._pending.get(key)
        if st is None or st["count"] != count:
            st = self._pending[key] = {"t0": now, "count": count, "parts": {}}
        st["parts"][idx] = chunk
        if sum(len(p) for p in st["parts"].values()) > self.limit:
            del self._pending[key]
            self.stats["oversize"] += 1
            return None
        if len(st["parts"]) == count:
            del self._pending[key]
            self.stats["completed"] += 1
            return b"".join(st["parts"][i] for i in range(count))
        return None


# --------------------------------------------------------------------------- gateway lines
FLAG_LETTERS = {"T": 0, "P": 1, "M": 2, "H": 3, "G": 4, "S": 5}
_LINE_FIELDS = {
    "F": ["temp_x100", "ppg_ir", "motion_mg", "hr_x1", "flags"],
    "S": ["vib_cg", "tilt_ddeg", "p_dhpa", "temp_x100", "gas_mv", "sound", "flags_hex"],
    "E": ["event_type_name", "level", "value_x1000"],
}


def letters_to_flags(letters: str) -> int:
    v = 0
    for ch in letters or "":
        if ch not in FLAG_LETTERS:
            raise FrameError(f"unknown flag letter {ch!r}")
        v |= 1 << FLAG_LETTERS[ch]
    return v


def parse_gateway_line(line: str) -> dict:
    """Parse a gateway text log line (PROTOCOL.md §3). Empty fields become None."""
    parts = line.strip().split(",")
    if len(parts) < 8 or parts[0] != "RX" or parts[3] not in _LINE_FIELDS:
        raise FrameError(f"not a gateway RX line: {line.strip()[:80]!r}")
    kind = parts[3]
    names = _LINE_FIELDS[kind]
    if len(parts) != 8 + len(names):
        raise FrameError(f"{kind} line needs {8 + len(names)} fields, got {len(parts)}")

    def num(s):
        return None if s == "" else int(s)

    out = {"kind": kind, "gateway_id": parts[1], "gw_ms": num(parts[2]), "device_id": parts[4],
           "boot_id": num(parts[5]), "sequence": num(parts[6]), "node_time_ms": num(parts[7])}
    for name, val in zip(names, parts[8:]):
        if name in ("flags", "event_type_name"):
            out[name] = val
        elif name == "flags_hex":
            out["flags"] = None if val == "" else int(val, 16)
        else:
            out[name] = num(val)
    if kind == "F":
        out["channel_flags"] = letters_to_flags(out["flags"])
    if None in (out["boot_id"], out["sequence"]):
        raise FrameError("boot_id and sequence are required")
    return out


# --------------------------------------------------------------------------- JSON conversion
def _scale(v, div):
    return None if v is None else round(v / div, 6)


def _times(received_at: str, node_time_ms, boot_epoch: Optional[float], uncertainty_s):
    """measured_at from a qualified boot epoch mapping; otherwise receive time with unknown uncertainty."""
    from .timeutil import from_epoch

    if boot_epoch is not None and node_time_ms is not None:
        return from_epoch(boot_epoch + node_time_ms / 1000.0), uncertainty_s
    return received_at, None


def physio_record(*, site_id, device_id, boot_id, sequence, measured_at, received_at, hr_bpm=None,
                  spo2_pct=None, skin_temp_c=None, motion_rms_g=None, quality=None, battery_pct=None,
                  data_origin="synthetic", scenario_id="unspecified", **ext) -> dict:
    rec = {"schema_version": SCHEMA_PHYSIO, "data_origin": data_origin, "scenario_id": scenario_id,
           "site_id": site_id, "device_id": device_id, "boot_id": boot_id, "sequence": sequence,
           "measured_at": measured_at, "received_at": received_at, "hr_bpm": hr_bpm, "spo2_pct": spo2_pct,
           "skin_temp_c": skin_temp_c, "motion_rms_g": motion_rms_g, "quality": quality,
           "battery_pct": battery_pct}
    rec.update({k: v for k, v in ext.items()})
    return rec


def frame_to_record(decoded: dict, *, site_id: str, received_at: str, scenario_id: str = "unspecified",
                    data_origin: str = "synthetic_payload_physical_transport", gateway_id: Optional[str] = None,
                    boot_epoch: Optional[float] = None, time_uncertainty_s: Optional[float] = None,
                    zone_map: Optional[dict] = None, frame_hex: Optional[str] = None) -> dict:
    """Convert a decoded PHYSIO/STATION/EVENT frame into a §5 JSON record."""
    h, p = decoded["header"], decoded["payload"]
    if not decoded.get("crc_ok"):
        raise FrameError("CRC mismatch; frame not converted")
    measured_at, unc = _times(received_at, h["node_time_ms"], boot_epoch, time_uncertainty_s)
    ext = {k: v for k, v in (("gateway_id", gateway_id), ("frame_hex", frame_hex)) if v is not None}
    ft = h["frame_type"]
    zone_map = zone_map or {}
    if ft == 1:
        cf = p["channel_flags"]
        return physio_record(
            site_id=site_id, device_id=h["device_id"], boot_id=h["boot_id"], sequence=h["sequence"],
            measured_at=measured_at, received_at=received_at, hr_bpm=_scale(p["hr"], 10),
            spo2_pct=_scale(p["spo2"], 10) if cf & 0x40 else None, skin_temp_c=_scale(p["skin_temp"], 100),
            motion_rms_g=_scale(p["motion_rms_mg"], 1000), quality=_scale(p["quality_pct"], 100),
            battery_pct=p["battery_pct"], data_origin=data_origin, scenario_id=scenario_id,
            ppg_ir=p["ppg_ir_mean"], channel_flags=cf, artifact_flags=p["artifact_flags"],
            hr_synthetic=bool(cf & 0x08), fw_build=p["fw_build"], time_uncertainty_s=unc, **ext)
    if ft == 2:
        fl = p["flags"]
        zone = zone_map.get(p["zone_code"], None if p["zone_code"] is None else f"zone-{p['zone_code']}")
        return {"schema_version": SCHEMA_STATION, "data_origin": data_origin, "scenario_id": scenario_id,
                "site_id": site_id, "zone_id": zone, "device_id": h["device_id"], "boot_id": h["boot_id"],
                "sequence": h["sequence"], "measured_at": measured_at, "received_at": received_at,
                "vib_peak_g": _scale(p["vib_peak_cg"], 100), "accel_rms_g": _scale(p["accel_rms_mg"], 1000),
                "tilt_deg": _scale(p["tilt_ddeg"], 10), "tilt_delta_deg": _scale(p["tilt_delta_ddeg"], 10),
                "pressure_hpa": _scale(p["pressure_dhpa"], 10), "pressure_delta_pa": p["pressure_delta_pa"],
                "temp_c": _scale(p["temp"], 100), "gas_v": _scale(p["gas_mv"], 1000),
                "sound_index": p["sound_index"],
                "pir_presence": bool(fl & 1) if p["sensor_flags"] & 0x10 else None,
                "sos": bool(fl & 2),
                # Attachment is an installation fact, never inferred from sensor values.
                "attachment_verified": False,
                "quality": _scale(p["quality_pct"], 100), "battery_pct": p["battery_pct"],
                "flags": fl, "sensor_flags": p["sensor_flags"], "fw_build": p["fw_build"], **ext}
    if ft == 3:
        name, unit = EVENT_TYPES.get(p["event_type"], (f"unknown_{p['event_type']}", None))
        zone = zone_map.get(p["zone_code"], None if p["zone_code"] is None else f"zone-{p['zone_code']}")
        prov = {"source": f"{SOURCE_CLASSES.get(h['source_class'], 'unknown')}:{h['device_id']}",
                "method": "node rule v%s" % p["rule_version"]}
        if name == "possible_impact_local":
            prov["method"] += "; unverified local composite (impact + loud/pressure within 2 s); not a strike attribution"
        if name == "gas_channel_alarm":
            prov["method"] += "; uncalibrated MQ-2 channel voltage"
        return {"schema_version": SCHEMA_EVENT, "data_origin": data_origin, "scenario_id": scenario_id,
                "site_id": site_id, "zone_id": zone,
                "event_id": f"{site_id}-{h['device_id']}-{h['boot_id']}-{h['sequence']}",
                "source_class": SOURCE_CLASSES.get(h["source_class"], "gateway"), "device_id": h["device_id"],
                "event_type": name, "level": LEVELS.get(p["level"], "info"), "value": _scale(p["value"], 1000),
                "unit": unit, "observed_at": measured_at, "reported_at": received_at,
                "time_uncertainty_s": unc, "rule_version": p["rule_version"], "quality": None,
                "ack_state": "unacknowledged", "provenance": prov, "boot_id": h["boot_id"],
                "sequence": h["sequence"], **ext}
    raise FrameError(f"frame_type {ft} is not a data record")


def line_to_record(parsed: dict, *, site_id: str, received_at: str, scenario_id: str = "unspecified",
                   data_origin: str = "synthetic_payload_physical_transport", boot_epoch: Optional[float] = None,
                   time_uncertainty_s: Optional[float] = None, zone_id: Optional[str] = None,
                   hr_synthetic: Optional[bool] = None) -> dict:
    """Convert a parsed gateway line into a §5 JSON record (scales per §3: temp x100, hr x1, motion mg)."""
    measured_at, unc = _times(received_at, parsed["node_time_ms"], boot_epoch, time_uncertainty_s)
    base = dict(site_id=site_id, device_id=parsed["device_id"], boot_id=parsed["boot_id"],
                sequence=parsed["sequence"])
    if parsed["kind"] == "F":
        cf = parsed["channel_flags"]
        syn = bool(cf & 0x08) if hr_synthetic is None else hr_synthetic
        return physio_record(**base, measured_at=measured_at, received_at=received_at,
                             hr_bpm=None if parsed["hr_x1"] is None else float(parsed["hr_x1"]),
                             skin_temp_c=_scale(parsed["temp_x100"], 100) if cf & 1 else None,
                             motion_rms_g=_scale(parsed["motion_mg"], 1000) if cf & 4 else None,
                             data_origin=data_origin, scenario_id=scenario_id, gateway_id=parsed["gateway_id"],
                             ppg_ir=parsed["ppg_ir"] if cf & 2 else None, channel_flags=cf, hr_synthetic=syn,
                             time_uncertainty_s=unc)
    if parsed["kind"] == "S":
        fl = parsed["flags"] or 0
        return {"schema_version": SCHEMA_STATION, "data_origin": data_origin, "scenario_id": scenario_id,
                **{"site_id": site_id, "zone_id": zone_id}, "device_id": parsed["device_id"],
                "boot_id": parsed["boot_id"], "sequence": parsed["sequence"], "measured_at": measured_at,
                "received_at": received_at, "vib_peak_g": _scale(parsed["vib_cg"], 100), "accel_rms_g": None,
                "tilt_deg": _scale(parsed["tilt_ddeg"], 10), "tilt_delta_deg": None,
                "pressure_hpa": _scale(parsed["p_dhpa"], 10), "pressure_delta_pa": None,
                "temp_c": _scale(parsed["temp_x100"], 100), "gas_v": _scale(parsed["gas_mv"], 1000),
                "sound_index": parsed["sound"], "pir_presence": bool(fl & 1), "sos": bool(fl & 2),
                "attachment_verified": False, "quality": None, "battery_pct": None,
                "gateway_id": parsed["gateway_id"], "flags": parsed["flags"]}
    name = parsed["event_type_name"]
    code = EVENT_CODES.get(name)
    unit = EVENT_TYPES[code][1] if code else None
    method = "gateway line"
    if name == "possible_impact_local":
        method += "; unverified local composite; not a strike attribution"
    return {"schema_version": SCHEMA_EVENT, "data_origin": data_origin, "scenario_id": scenario_id,
            "site_id": site_id, "zone_id": zone_id,
            "event_id": f"{site_id}-{parsed['device_id']}-{parsed['boot_id']}-{parsed['sequence']}",
            "source_class": "gateway" if name in ("link_loss", "link_restored") else "stationary_node",
            "device_id": parsed["device_id"], "event_type": name,
            "level": LEVELS.get(parsed["level"], "info"), "value": _scale(parsed["value_x1000"], 1000),
            "unit": unit, "observed_at": measured_at, "reported_at": received_at, "time_uncertainty_s": unc,
            "rule_version": None, "quality": None, "ack_state": "unacknowledged",
            "provenance": {"source": f"gateway:{parsed['gateway_id']}", "method": method},
            "boot_id": parsed["boot_id"], "sequence": parsed["sequence"], "gateway_id": parsed["gateway_id"]}


# --------------------------------------------------------------------------- test vectors
def flatten_decoded(decoded: dict) -> dict:
    flat = dict(decoded["header"])
    flat.update(decoded["payload"])
    flat["crc_ok"] = decoded["crc_ok"]
    return flat


def check_vector(vec: dict) -> list[str]:
    """Return a list of mismatch descriptions for one vector (empty = pass)."""
    try:
        dec = decode_any(bytes.fromhex(vec["hex"]))
    except FrameError as exc:
        return [f"decode error: {exc}"] if not vec.get("expect_error") else []
    if vec.get("expect_error"):
        return ["expected a decode error"]
    exp = vec.get("expected", {})
    errors = []
    if any(k in exp for k in ("header", "payload")):
        for part in ("header", "payload"):
            for k, v in exp.get(part, {}).items():
                if dec[part].get(k, "<missing>") != v:
                    errors.append(f"{part}.{k}: got {dec[part].get(k, '<missing>')!r}, expected {v!r}")
        if "crc_ok" in exp and dec["crc_ok"] != exp["crc_ok"]:
            errors.append(f"crc_ok: got {dec['crc_ok']}, expected {exp['crc_ok']}")
    else:
        flat = flatten_decoded(dec)
        for k, v in exp.items():
            if flat.get(k, "<missing>") != v:
                errors.append(f"{k}: got {flat.get(k, '<missing>')!r}, expected {v!r}")
    return errors


def load_test_vectors(path) -> dict:
    """Check a JSON list of ``{"name", "hex", "expected"}`` vectors. Returns a report dict."""
    with open(path, encoding="utf-8") as fh:
        vectors = json.load(fh)
    if isinstance(vectors, dict):
        vectors = vectors.get("vectors", [])
    results = [{"name": v.get("name"), "errors": check_vector(v)} for v in vectors]
    failed = [r for r in results if r["errors"]]
    return {"total": len(results), "passed": len(results) - len(failed), "failed": failed}
