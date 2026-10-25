"""Builders for §5 JSON records used by the synthetic generators."""

from __future__ import annotations

from typing import Optional

from . import SCHEMA_EVENT, SCHEMA_STATION
from .frames import physio_record

__all__ = ["physio_record", "station_record", "event_record", "STATION_FIELDS", "UNITS"]

STATION_FIELDS = ("vib_peak_g", "accel_rms_g", "tilt_deg", "tilt_delta_deg", "pressure_hpa", "pressure_delta_pa",
                  "temp_c", "gas_v", "sound_index", "pir_presence", "sos", "quality", "battery_pct")
UNITS = {"sos": "1", "sos_reset": "1", "impact_excursion": "g", "loud_sound": "index", "gas_channel_alarm": "V",
         "tilt_change": "deg", "pressure_transient": "Pa", "presence": "1/0", "link_loss": "s",
         "possible_impact_local": "g", "help_request": "1", "link_restored": "s", "buffer_eviction": "count"}


def station_record(*, site_id, zone_id, device_id, boot_id, sequence, measured_at, received_at,
                   data_origin="synthetic", scenario_id="unspecified", attachment_verified=False, **values) -> dict:
    rec = {"schema_version": SCHEMA_STATION, "data_origin": data_origin, "scenario_id": scenario_id,
           "site_id": site_id, "zone_id": zone_id, "device_id": device_id, "boot_id": boot_id,
           "sequence": sequence, "measured_at": measured_at, "received_at": received_at}
    for k in STATION_FIELDS:
        rec[k] = values.pop(k, None)
    rec["attachment_verified"] = attachment_verified
    rec.update(values)
    return rec


def event_record(*, site_id, zone_id, event_id, source_class, device_id, event_type, level, observed_at,
                 reported_at, provenance, value=None, unit: Optional[str] = "", time_uncertainty_s=None,
                 rule_version=None, quality=None, ack_state="unacknowledged", data_origin="synthetic",
                 scenario_id="unspecified", **ext) -> dict:
    rec = {"schema_version": SCHEMA_EVENT, "data_origin": data_origin, "scenario_id": scenario_id,
           "site_id": site_id, "zone_id": zone_id, "event_id": event_id, "source_class": source_class,
           "device_id": device_id, "event_type": event_type, "level": level, "value": value,
           "unit": UNITS.get(event_type) if unit == "" else unit, "observed_at": observed_at,
           "reported_at": reported_at, "time_uncertainty_s": time_uncertainty_s, "rule_version": rule_version,
           "quality": quality, "ack_state": ack_state, "provenance": provenance}
    rec.update(ext)
    return rec
