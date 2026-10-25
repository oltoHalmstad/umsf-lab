"""Live ingestion adapters (optional dependencies are imported lazily).

* ``serial_gateway`` - gateway text lines from a serial port (pyserial) or any text stream.
* ``mqtt_ingest``    - MQTT/TLS mutual-auth subscriber (paho-mqtt); app ACK only after COMMIT.
* ``ble_direct``     - BLE central for bench use (bleak); fragment reassembly; ACK frames.

None of these has been validated against hardware in this package; unit tests use fakes.
"""

from __future__ import annotations

from typing import Optional


class BootClockEstimator:
    """Map node uptime to wall-clock time per (device, boot) from first observed arrivals.

    The estimate ``boot_epoch = min(received - node_time)`` gives an *upper bound* on capture
    age only under the assumption of bounded delivery delay; it is not a qualified time mapping,
    so records carry ``time_uncertainty_s = None`` (unknown) unless a bound is configured.
    """

    def __init__(self, uncertainty_s: Optional[float] = None):
        self.uncertainty_s = uncertainty_s
        self._epochs: dict = {}

    def epoch(self, device_id: str, boot_id: int, node_time_ms: int, received_epoch: float) -> float:
        key = (device_id, boot_id)
        cand = received_epoch - node_time_ms / 1000.0
        if key not in self._epochs or cand < self._epochs[key]:
            self._epochs[key] = cand
        return self._epochs[key]


class AckTracker:
    """Cumulative application ACK state: highest contiguous committed sequence per (device, boot)."""

    def __init__(self):
        self.committed: dict = {}
        self.acked: dict = {}

    def commit(self, device_id: str, boot_id: int, sequence: int) -> Optional[int]:
        """Record a committed identity; return a new ack_up_to_seq if it advanced, else None."""
        key = (device_id, boot_id)
        self.committed.setdefault(key, set()).add(sequence)
        cur = self.acked.get(key, 0)
        nxt = cur
        while nxt + 1 in self.committed[key]:
            nxt += 1
        if nxt > cur:
            self.acked[key] = nxt
            self.committed[key] = {s for s in self.committed[key] if s > nxt}
            return nxt
        return None
