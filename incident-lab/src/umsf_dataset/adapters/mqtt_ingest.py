"""MQTT ingestion (gateway -> site broker, PROTOCOL.md §4) with application ACK after COMMIT.

Topics: ``umsf/<site>/<gw>/{physio,station,event,status}``; ACK to ``umsf/<site>/ack/<gw>`` with
``{"device_id","boot_id","ack_up_to_seq"}``. The ACK is published only after the store's
durable COMMIT returns; an MQTT QoS 1 broker acknowledgement does NOT authorise deletion from
node buffers. If a record carries ``frame_hex``, the frame is decoded, its CRC checked and its
identity compared with the JSON identity before acceptance.

``paho-mqtt`` is optional and imported lazily in :meth:`MqttIngest.connect`. TLS 1.3 with
mutual authentication (CA, client certificate and key) is required by default.
"""

from __future__ import annotations

import json
import ssl
from typing import Optional

from .. import frames
from . import AckTracker

DATA_KINDS = ("physio", "station", "event")


class MqttIngest:
    def __init__(self, store, site_id: str, *, client=None, allow_measured: bool = False, ack_qos: int = 1):
        self.store, self.site_id, self.client = store, site_id, client
        self.allow_measured, self.ack_qos = allow_measured, ack_qos
        self.acks = AckTracker()
        self.counts = {"inserted": 0, "duplicate": 0, "conflict": 0, "rejected": 0, "status": 0, "acks_sent": 0}
        self.gateway_status: dict = {}

    # ---------------------------------------------------------------- message handling
    def parse_topic(self, topic: str):
        parts = topic.split("/")
        if len(parts) != 4 or parts[0] != "umsf" or parts[1] != self.site_id or parts[2] == "ack":
            return None
        return parts[2], parts[3]

    def _check_frame(self, rec: dict) -> Optional[str]:
        fh = rec.get("frame_hex")
        if not fh:
            return None
        try:
            dec = frames.decode_frame(bytes.fromhex(fh))
        except (frames.FrameError, ValueError) as exc:
            return f"frame_hex undecodable: {exc}"
        if not dec["crc_ok"]:
            return "frame_hex CRC mismatch"
        h = dec["header"]
        if "sequence" in rec and (h["boot_id"], h["sequence"]) != (rec.get("boot_id"), rec.get("sequence")):
            return "frame_hex identity differs from JSON identity"
        return None

    def handle_message(self, topic: str, payload: bytes) -> str:
        parsed = self.parse_topic(topic)
        if parsed is None:
            return "ignored"
        gw, kind = parsed
        if kind == "status":
            try:
                self.gateway_status[gw] = json.loads(payload)
            except ValueError:
                pass
            self.counts["status"] += 1
            return "status"
        if kind not in DATA_KINDS:
            return "ignored"
        text = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
        try:
            rec = json.loads(text)
        except ValueError:
            rec = None
        err = self._check_frame(rec) if isinstance(rec, dict) else None
        if err:
            self.store.bump("lines")
            status = self.store.reject(err, text, f"mqtt:{gw}")
        else:
            status = self.store.ingest_line(text, source=f"mqtt:{gw}", allow_measured=self.allow_measured)
        self.store.commit()  # durable COMMIT before any application ACK
        self.counts[status] += 1
        if status in ("inserted", "duplicate") and isinstance(rec, dict) and kind != "event":
            nxt = self.acks.commit(rec["device_id"], rec["boot_id"], rec["sequence"])
            if nxt is not None:
                self.send_ack(gw, rec["device_id"], rec["boot_id"], nxt)
        return status

    def send_ack(self, gw: str, device_id: str, boot_id: int, ack_up_to_seq: int):
        msg = json.dumps({"device_id": device_id, "boot_id": boot_id, "ack_up_to_seq": ack_up_to_seq})
        if self.client is not None:
            self.client.publish(f"umsf/{self.site_id}/ack/{gw}", msg, qos=self.ack_qos)
        self.counts["acks_sent"] += 1

    # ---------------------------------------------------------------- live connection
    def connect(self, host: str, port: int = 8883, *, ca_certs: str, certfile: str, keyfile: str,
                client_id: str = "umsf-dataset-agent", keepalive: int = 30):  # pragma: no cover - needs broker
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("paho-mqtt is required: pip install 'umsf-incident-dataset[live]'") from exc
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        except AttributeError:
            client = mqtt.Client(client_id=client_id)
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_certs)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.load_cert_chain(certfile, keyfile)  # mutual authentication
        client.tls_set_context(ctx)

        def on_connect(c, *_a, **_k):
            for kind in DATA_KINDS + ("status",):
                c.subscribe(f"umsf/{self.site_id}/+/{kind}", qos=1)

        client.on_connect = on_connect
        client.on_message = lambda c, u, m: self.handle_message(m.topic, m.payload)
        self.client = client
        client.connect(host, port, keepalive)
        return client
