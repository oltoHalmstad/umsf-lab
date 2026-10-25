"""Direct BLE central for bench use (bleak, optional). Not a production gateway.

Subscribes to TELEMETRY, EVENT (fragmented, 4-byte fragment header) and COMPACT (20-byte,
no fragment header) characteristics of a UMSF node, reassembles fragments (512-byte limit,
2 s timeout), decodes frames, stores records, and writes a cumulative ACK frame only after the
store COMMIT. COMPACT packets update an in-memory latest-state table with 2 s staleness; they
carry no boot identity and are not stored as measurement identities.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Optional

from .. import frames
from ..timeutil import fmt_iso, to_epoch
from . import AckTracker, BootClockEstimator

SERVICE_UUID = "6e5a0001-55f0-4c1b-9b6a-0d3c2b7a5e01"
TELEMETRY_UUID = "6e5a0002-55f0-4c1b-9b6a-0d3c2b7a5e01"
EVENT_UUID = "6e5a0003-55f0-4c1b-9b6a-0d3c2b7a5e01"
ACK_UUID = "6e5a0004-55f0-4c1b-9b6a-0d3c2b7a5e01"
STATUS_UUID = "6e5a0005-55f0-4c1b-9b6a-0d3c2b7a5e01"
CONFIG_UUID = "6e5a0006-55f0-4c1b-9b6a-0d3c2b7a5e01"
COMPACT_UUID = "6e5a0007-55f0-4c1b-9b6a-0d3c2b7a5e01"
COMPACT_STALE_S = 2.0


def _now() -> str:
    return fmt_iso(datetime.now(timezone.utc))


class BleDirectCollector:
    def __init__(self, store, site_id: str, *, gateway_id: str = "PC1", scenario_id: str = "ble-bench",
                 data_origin: str = "synthetic_payload_physical_transport", clock: Callable[[], str] = _now,
                 monotonic: Callable[[], float] = time.monotonic, ack_writer: Optional[Callable[[bytes], None]] = None,
                 zone_map: Optional[dict] = None):
        self.store, self.site_id, self.gateway_id = store, site_id, gateway_id
        self.scenario_id, self.data_origin, self.clock, self.monotonic = scenario_id, data_origin, clock, monotonic
        self.reassembler = frames.Reassembler(clock=monotonic)
        self.boot_clock = BootClockEstimator()
        self.acks = AckTracker()
        self.ack_writer = ack_writer
        self.zone_map = zone_map or {}
        self.compact_state: dict = {}
        self.last_status: Optional[dict] = None
        self.counts = {"frames": 0, "crc_fail": 0, "inserted": 0, "duplicate": 0, "conflict": 0, "rejected": 0,
                       "compact": 0, "acks_written": 0}
        self._ack_seq = 0

    def handle_notification(self, char_uuid: str, data: bytes, source: str = "node") -> Optional[str]:
        char_uuid = char_uuid.lower()
        if char_uuid == COMPACT_UUID:
            dec = frames.decode_compact(data)
            if dec["crc_ok"]:
                self.compact_state[dec["header"]["node_index"]] = {"t": self.monotonic(), **dec}
                self.counts["compact"] += 1
                return "compact"
            self.counts["crc_fail"] += 1
            return "crc_fail"
        if char_uuid == STATUS_UUID:
            return self._handle_frame(data)
        frame = self.reassembler.feed(data, source=source + char_uuid)
        return None if frame is None else self._handle_frame(frame)

    def _handle_frame(self, frame: bytes) -> str:
        self.counts["frames"] += 1
        recv = self.clock()
        try:
            dec = frames.decode_frame(frame)
        except frames.FrameError as exc:
            self.store.bump("lines")
            self.counts["rejected"] += 1
            return self.store.reject(str(exc), frame.hex(), "ble")
        if not dec["crc_ok"]:
            self.counts["crc_fail"] += 1
            self.store.bump("lines")
            self.counts["rejected"] += 1
            return self.store.reject("CRC mismatch", frame.hex(), "ble")
        h = dec["header"]
        if h["frame_type"] == 4:
            self.last_status = dec
            return "status"
        if h["frame_type"] not in (1, 2, 3):
            return "ignored"
        epoch = self.boot_clock.epoch(h["device_id"], h["boot_id"], h["node_time_ms"], to_epoch(recv))
        rec = frames.frame_to_record(dec, site_id=self.site_id, received_at=recv, scenario_id=self.scenario_id,
                                     data_origin=self.data_origin, gateway_id=self.gateway_id, boot_epoch=epoch,
                                     zone_map=self.zone_map, frame_hex=frame.hex())
        status = self.store.ingest_obj(rec, source="ble")
        self.store.commit()  # durable COMMIT precedes the application ACK
        self.counts[status] += 1
        if status in ("inserted", "duplicate"):
            nxt = self.acks.commit(h["device_id"], h["boot_id"], h["sequence"])
            if nxt is not None:
                self.write_ack(h["boot_id"], nxt)
        return status

    def ack_frame(self, boot_id: int, ack_up_to_seq: int) -> bytes:
        self._ack_seq += 1
        return frames.encode_frame(5, {"source_class": 3, "device_id": self.gateway_id[:4], "boot_id": 0,
                                       "sequence": self._ack_seq, "node_time_ms": 0},
                                   {"target_boot_id": boot_id, "reserved": 0, "ack_up_to_seq": ack_up_to_seq})

    def write_ack(self, boot_id: int, ack_up_to_seq: int):
        frame = self.ack_frame(boot_id, ack_up_to_seq)
        if self.ack_writer is not None:
            self.ack_writer(frame)
        self.counts["acks_written"] += 1

    def compact_snapshot(self) -> dict:
        now = self.monotonic()
        return {idx: {"stale": now - st["t"] > COMPACT_STALE_S, "age_s": round(now - st["t"], 3),
                      "payload": st["payload"], "seq": st["header"]["seq"]} for idx, st in self.compact_state.items()}

    async def run(self, address: str, duration_s: float = 60.0):  # pragma: no cover - needs hardware
        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise RuntimeError("bleak is required: pip install 'umsf-incident-dataset[live]'") from exc
        import asyncio

        async with BleakClient(address) as client:
            pending = []
            self.ack_writer = lambda b: pending.append(b)
            for uuid in (TELEMETRY_UUID, EVENT_UUID, COMPACT_UUID, STATUS_UUID):
                await client.start_notify(uuid, lambda ch, d, u=uuid: self.handle_notification(u, bytes(d), address))
            end = time.monotonic() + duration_s
            while time.monotonic() < end:
                while pending:
                    await client.write_gatt_char(ACK_UUID, pending.pop(0), response=True)
                await asyncio.sleep(0.1)
