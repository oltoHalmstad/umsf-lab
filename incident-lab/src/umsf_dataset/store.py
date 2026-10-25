"""Durable SQLite store with identity-based deduplication and conflict quarantine.

* WAL journal + ``synchronous=FULL`` (manuscript Sec. 3.3.8).
* Unique measurement key (site_id, device_id, boot_id, sequence); events keyed by (site_id, event_id).
* Identical redelivery is idempotent. A changed immutable payload under the same identity
  quarantines the *whole* identity: it is excluded from exports and aggregates and both
  versions are retained in the audit table ``quarantine``.
* ``received_at`` is stored separately from ``measured_at``; ``measured_at`` is never rewritten.
* Orderly close/reopen is tested; abrupt power-loss durability is NOT tested by this package.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from . import frames
from .timeutil import fmt_iso, to_epoch
from .validate import validate_line, validate_record

MUTABLE_KEYS = {"received_at", "gateway_id", "reported_at"}
KINDS = ("physio", "station", "event")
_TABLE = {"physio": "physio", "station": "station", "event": "events"}

_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS physio (
  id INTEGER PRIMARY KEY, site_id TEXT NOT NULL, device_id TEXT NOT NULL, boot_id INTEGER NOT NULL,
  sequence INTEGER NOT NULL, measured_at TEXT NOT NULL, received_at TEXT NOT NULL,
  measured_ts REAL NOT NULL, received_ts REAL NOT NULL, payload_hash TEXT NOT NULL,
  record_json TEXT NOT NULL, quarantined INTEGER NOT NULL DEFAULT 0,
  UNIQUE (site_id, device_id, boot_id, sequence));
CREATE TABLE IF NOT EXISTS station (
  id INTEGER PRIMARY KEY, site_id TEXT NOT NULL, device_id TEXT NOT NULL, boot_id INTEGER NOT NULL,
  sequence INTEGER NOT NULL, measured_at TEXT NOT NULL, received_at TEXT NOT NULL,
  measured_ts REAL NOT NULL, received_ts REAL NOT NULL, payload_hash TEXT NOT NULL,
  record_json TEXT NOT NULL, quarantined INTEGER NOT NULL DEFAULT 0,
  UNIQUE (site_id, device_id, boot_id, sequence));
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, site_id TEXT NOT NULL, event_id TEXT NOT NULL, device_id TEXT NOT NULL,
  event_type TEXT NOT NULL, source_class TEXT NOT NULL, measured_at TEXT, received_at TEXT NOT NULL,
  measured_ts REAL, received_ts REAL NOT NULL, payload_hash TEXT NOT NULL, record_json TEXT NOT NULL,
  quarantined INTEGER NOT NULL DEFAULT 0, UNIQUE (site_id, event_id));
CREATE TABLE IF NOT EXISTS quarantine (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, identity TEXT NOT NULL, first_hash TEXT NOT NULL,
  conflicting_hash TEXT NOT NULL, conflicting_json TEXT NOT NULL, detected_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rejects (
  id INTEGER PRIMARY KEY, source TEXT, line_no INTEGER, reason TEXT NOT NULL, raw TEXT, detected_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS physio_measured ON physio (site_id, measured_ts);
CREATE INDEX IF NOT EXISTS station_measured ON station (site_id, measured_ts);
"""


def payload_hash(record: dict) -> str:
    """SHA-256 over the canonical JSON of the immutable part of a record."""
    core = {k: v for k, v in record.items() if k not in MUTABLE_KEYS}
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _identity(kind: str, rec: dict) -> tuple:
    if kind == "event":
        return (rec["site_id"], rec["event_id"])
    return (rec["site_id"], rec["device_id"], rec["boot_id"], rec["sequence"])


def _now_iso() -> str:
    return fmt_iso(datetime.now(timezone.utc))


class Store:
    def __init__(self, path: str = ":memory:", clock=_now_iso):
        """``clock`` stamps audit rows (detected_at); pass a fixed clock for reproducible runs."""
        self.path, self.clock = path, clock
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript(_DDL)
        self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('created_at', ?)", (self.clock(),))
        self._in_tx = False

    # ------------------------------------------------------------------ transactions
    def begin(self):
        if not self._in_tx:
            self.conn.execute("BEGIN IMMEDIATE")
            self._in_tx = True

    def commit(self):
        """Durable COMMIT. Application ACKs may only be issued after this returns."""
        if self._in_tx:
            self.conn.execute("COMMIT")
            self._in_tx = False

    def rollback(self):
        if self._in_tx:
            self.conn.execute("ROLLBACK")
            self._in_tx = False

    def close(self):
        self.commit()
        self.conn.close()

    def pragmas(self) -> dict:
        return {"journal_mode": self.conn.execute("PRAGMA journal_mode").fetchone()[0],
                "synchronous": {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}[
                    self.conn.execute("PRAGMA synchronous").fetchone()[0]],
                "integrity_check": self.conn.execute("PRAGMA integrity_check").fetchone()[0]}

    # ------------------------------------------------------------------ counters
    def bump(self, name: str, n: int = 1):
        self.conn.execute("INSERT INTO counters VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = value + ?",
                          (name, n, n))

    def counters(self) -> dict:
        return dict(self.conn.execute("SELECT name, value FROM counters ORDER BY name").fetchall())

    # ------------------------------------------------------------------ ingestion
    def ingest_record(self, rec: dict, kind: str) -> str:
        """Insert a validated record. Returns inserted | duplicate | conflict."""
        self.begin()
        table, ident, h = _TABLE[kind], _identity(kind, rec), payload_hash(rec)
        if kind == "event":
            row = self.conn.execute("SELECT id, payload_hash FROM events WHERE site_id=? AND event_id=?",
                                    ident).fetchone()
        else:
            row = self.conn.execute(f"SELECT id, payload_hash FROM {table} WHERE site_id=? AND device_id=? "
                                    "AND boot_id=? AND sequence=?", ident).fetchone()
        if row is None:
            js = json.dumps(rec, sort_keys=True, separators=(",", ":"))
            if kind == "event":
                obs = rec.get("observed_at")
                self.conn.execute(
                    "INSERT INTO events (site_id, event_id, device_id, event_type, source_class, measured_at, "
                    "received_at, measured_ts, received_ts, payload_hash, record_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (rec["site_id"], rec["event_id"], rec["device_id"], rec["event_type"], rec["source_class"],
                     obs, rec["reported_at"], to_epoch(obs) if obs else None, to_epoch(rec["reported_at"]), h, js))
            else:
                self.conn.execute(
                    f"INSERT INTO {table} (site_id, device_id, boot_id, sequence, measured_at, received_at, "
                    "measured_ts, received_ts, payload_hash, record_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (*ident, rec["measured_at"], rec["received_at"], to_epoch(rec["measured_at"]),
                     to_epoch(rec["received_at"]), h, js))
            self.bump(f"{kind}_inserted")
            return "inserted"
        rid, first_hash = row
        ident_s = "|".join(map(str, ident))
        known = {r[0] for r in self.conn.execute(
            "SELECT conflicting_hash FROM quarantine WHERE kind=? AND identity=?", (kind, ident_s))}
        if h == first_hash or h in known:
            self.bump(f"{kind}_duplicates")
            return "duplicate"
        self.conn.execute(f"UPDATE {table} SET quarantined=1 WHERE id=?", (rid,))
        self.conn.execute("INSERT INTO quarantine (kind, identity, first_hash, conflicting_hash, conflicting_json, "
                          "detected_at) VALUES (?,?,?,?,?,?)",
                          (kind, ident_s, first_hash, h, json.dumps(rec, sort_keys=True), self.clock()))
        self.bump(f"{kind}_conflicts")
        return "conflict"

    def reject(self, reason: str, raw: str = "", source: str = "", line_no: Optional[int] = None):
        self.begin()
        self.conn.execute("INSERT INTO rejects (source, line_no, reason, raw, detected_at) VALUES (?,?,?,?,?)",
                          (source, line_no, reason[:500], (raw or "")[:2000], self.clock()))
        self.bump("rejected")
        return "rejected"

    def ingest_line(self, line: str, *, source: str = "", line_no: Optional[int] = None,
                    allow_measured: bool = False) -> str:
        self.bump("lines")
        kind, obj, errs = validate_line(line, allow_measured=allow_measured)
        if errs:
            return self.reject("; ".join(errs), line.rstrip("\n"), source, line_no)
        return self.ingest_record(obj, kind)

    def ingest_obj(self, obj: dict, *, source: str = "", allow_measured: bool = False) -> str:
        self.bump("lines")
        kind, errs = validate_record(obj, allow_measured)
        if errs:
            return self.reject("; ".join(errs), json.dumps(obj)[:2000], source)
        return self.ingest_record(obj, kind)

    def ingest_jsonl(self, lines: Iterable[str], source: str = "", allow_measured: bool = False) -> dict:
        res = {"lines": 0, "inserted": 0, "duplicate": 0, "conflict": 0, "rejected": 0}
        for i, line in enumerate(lines, 1):
            if not line.strip():
                continue
            res["lines"] += 1
            res[self.ingest_line(line, source=source, line_no=i, allow_measured=allow_measured)] += 1
        self.commit()
        return res

    def ingest_gateway_lines(self, lines: Iterable[str], *, site_id: str, received_at: Optional[str] = None,
                             source: str = "", **conv) -> dict:
        """Ingest gateway text lines (§3). Non-RX lines are skipped; malformed RX lines are rejected."""
        res = {"lines": 0, "inserted": 0, "duplicate": 0, "conflict": 0, "rejected": 0}
        for i, line in enumerate(lines, 1):
            if not line.startswith("RX,"):
                continue
            res["lines"] += 1
            try:
                rec = frames.line_to_record(frames.parse_gateway_line(line), site_id=site_id,
                                            received_at=received_at or _now_iso(), **conv)
            except (frames.FrameError, ValueError, KeyError) as exc:
                self.bump("lines")
                res[self.reject(str(exc), line, source, i)] += 1
                continue
            res[self.ingest_obj(rec, source=source)] += 1
        self.commit()
        return res

    def ingest_frames_hex(self, lines: Iterable[str], *, site_id: str, source: str = "", **conv) -> dict:
        """Ingest lines ``[<received_at> ]<hex>`` holding complete frames; CRC failures are rejected."""
        res = {"lines": 0, "inserted": 0, "duplicate": 0, "conflict": 0, "rejected": 0}
        for i, line in enumerate(lines, 1):
            parts = line.split()
            if not parts:
                continue
            res["lines"] += 1
            recv = parts[0] if len(parts) == 2 else _now_iso()
            try:
                dec = frames.decode_frame(bytes.fromhex(parts[-1]))
                rec = frames.frame_to_record(dec, site_id=site_id, received_at=recv, frame_hex=parts[-1].lower(),
                                             **conv)
            except (frames.FrameError, ValueError) as exc:
                self.bump("lines")
                res[self.reject(str(exc), line.strip(), source, i)] += 1
                continue
            res[self.ingest_obj(rec, source=source)] += 1
        self.commit()
        return res

    # ------------------------------------------------------------------ queries
    def records(self, kind: str, *, include_quarantined: bool = False, received_by: Optional[float] = None,
                site_id: Optional[str] = None) -> list[dict]:
        sql = f"SELECT record_json, quarantined FROM {_TABLE[kind]} WHERE 1=1"
        args: list = []
        if not include_quarantined:
            sql += " AND quarantined=0"
        if received_by is not None:
            sql += " AND received_ts <= ?"
            args.append(received_by)
        if site_id is not None:
            sql += " AND site_id = ?"
            args.append(site_id)
        sql += " ORDER BY measured_ts, id" if kind != "event" else " ORDER BY COALESCE(measured_ts, received_ts), id"
        return [json.loads(r[0]) for r in self.conn.execute(sql, args)]

    def count(self, kind: str, include_quarantined: bool = True) -> int:
        sql = f"SELECT COUNT(*) FROM {_TABLE[kind]}" + ("" if include_quarantined else " WHERE quarantined=0")
        return self.conn.execute(sql).fetchone()[0]

    def quarantined_identities(self) -> list[dict]:
        out = []
        for kind in KINDS:
            for (js,) in self.conn.execute(f"SELECT record_json FROM {_TABLE[kind]} WHERE quarantined=1"):
                out.append({"kind": kind, "record": json.loads(js)})
        return out

    def quarantine_log(self) -> list[dict]:
        cols = ("kind", "identity", "first_hash", "conflicting_hash", "conflicting_json", "detected_at")
        rows = self.conn.execute(f"SELECT {', '.join(cols)} FROM quarantine ORDER BY id").fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def rejects(self) -> list[dict]:
        cols = ("source", "line_no", "reason", "raw", "detected_at")
        return [dict(zip(cols, r)) for r in self.conn.execute(f"SELECT {', '.join(cols)} FROM rejects ORDER BY id")]

    def stats(self) -> dict:
        c = self.counters()
        return {"lines": c.get("lines", 0),
                "unique_identities": sum(self.count(k) for k in ("physio", "station")),
                "unique_events": self.count("event"),
                "duplicates": sum(c.get(f"{k}_duplicates", 0) for k in KINDS),
                "conflicts": sum(c.get(f"{k}_conflicts", 0) for k in KINDS),
                "quarantined_identities": len(self.quarantined_identities()),
                "rejected": c.get("rejected", 0),
                "exportable_physio": self.count("physio", False), "exportable_station": self.count("station", False),
                "exportable_events": self.count("event", False)}
