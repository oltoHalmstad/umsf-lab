"""Read gateway text lines (PROTOCOL.md §3) from a serial port, a file or stdin and ingest them.

``pyserial`` is optional and imported only when a serial port is opened. Lines that do not start
with ``RX,`` (boot banners, debug output) are ignored; malformed RX lines are rejected and logged.
Receive time is stamped by this host when the line is read; node and gateway millisecond fields
do not share a clock and are never subtracted to estimate latency.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional, TextIO

from .. import frames
from ..timeutil import fmt_iso, to_epoch
from . import BootClockEstimator


def _now() -> str:
    return fmt_iso(datetime.now(timezone.utc))


def open_serial(port: str, baud: int = 115200):  # pragma: no cover - needs hardware
    try:
        import serial  # pyserial
    except ImportError as exc:
        raise RuntimeError("pyserial is required for serial ports: pip install pyserial") from exc
    ser = serial.Serial(port, baud, timeout=1)
    return (raw.decode("utf-8", "replace") for raw in iter(ser.readline, None))


class SerialGatewayIngest:
    def __init__(self, store, site_id: str, *, scenario_id: str = "live-gateway",
                 data_origin: str = "synthetic_payload_physical_transport", clock: Callable[[], str] = _now,
                 estimate_clock: bool = True, zone_id: Optional[str] = None):
        self.store, self.site_id, self.clock = store, site_id, clock
        self.scenario_id, self.data_origin, self.zone_id = scenario_id, data_origin, zone_id
        self.boot_clock = BootClockEstimator() if estimate_clock else None
        self.counts = {"ignored": 0, "inserted": 0, "duplicate": 0, "conflict": 0, "rejected": 0}

    def process_line(self, line: str) -> str:
        line = line.strip()
        if not line.startswith("RX,"):
            self.counts["ignored"] += 1
            return "ignored"
        recv = self.clock()
        try:
            p = frames.parse_gateway_line(line)
            epoch = None
            if self.boot_clock is not None and p["node_time_ms"] is not None:
                epoch = self.boot_clock.epoch(p["device_id"], p["boot_id"], p["node_time_ms"], to_epoch(recv))
            rec = frames.line_to_record(p, site_id=self.site_id, received_at=recv, scenario_id=self.scenario_id,
                                        data_origin=self.data_origin, boot_epoch=epoch, zone_id=self.zone_id)
        except (frames.FrameError, ValueError) as exc:
            self.store.bump("lines")
            status = self.store.reject(str(exc), line, "serial")
        else:
            status = self.store.ingest_obj(rec, source="serial")
        self.store.commit()
        self.counts[status] += 1
        return status

    def run(self, lines: Iterable[str], max_lines: Optional[int] = None) -> dict:
        for i, line in enumerate(lines):
            if max_lines is not None and i >= max_lines:
                break
            self.process_line(line)
        return dict(self.counts)


def run_stdin(store, site_id: str, stream: TextIO = sys.stdin, **kw) -> dict:
    return SerialGatewayIngest(store, site_id, **kw).run(stream)
