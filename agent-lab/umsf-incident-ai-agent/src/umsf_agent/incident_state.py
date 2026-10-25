"""Source-qualified zone incident state, Torstensson et al. (2026) Sec. 3.8.

    S_z(t) = (M_z, H_z, P_z, F_z, U_z)                                     (6)

M mechanical observations and authorised structural assessments, H hazard
observations, P personnel accounting / assistance information, F functional
availability and residual capacity, U observation gaps, uncertain clocks,
contradictions and unavailable qualifications. These are lists of typed,
source-qualified assertions -- never averaged into a destruction score.

    T_report = t_p - t_e,   T_action = t_a - t_e                            (7)

Rules enforced:
* strike attribution comes only from `authoritative_external_alert`;
  `possible_impact_local` is a local composite shown as UNVERIFIED;
* a stale assertion stays in history but loses current authority;
* link loss / silence -> observation gap with last known state, never
  "collapse" or "casualty";
* a node with uncertain attachment loses its structural interpretation;
* acoustic / PIR outputs are possible presence cues only (not vital signs).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional

from .ingest import Dataset
from .util import fmt_ts, parse_ts, sha256_obj

LAYERS = ("M", "H", "P", "F", "U")

# Permissible initial outputs (Table 8) per event type.
SEMANTICS = {
    "impact_excursion": ("M", "channel excursion (acceleration), uncalibrated; not a damage measure"),
    "tilt_change": ("M", "orientation change of node; structural meaning requires verified mounting"),
    "pressure_transient": ("M", "pressure transient in channel; not a blast estimate"),
    "loud_sound": ("M", "acoustic transient; not an explosion classification"),
    "possible_impact_local": ("M", "possible_impact_local: local composite cue, UNVERIFIED; not a strike attribution"),
    "structural_assessment": ("M", "structural assessment by named assessor (scope/method/validity attached)"),
    "gas_channel_alarm": ("H", "uncalibrated gas-channel response (MQ-2); not a concentration or identification"),
    "sos": ("P", "direct assistance request (SOS)"),
    "sos_reset": ("P", "SOS reset by local operator (recorded action, not proof of rescue)"),
    "help_request": ("P", "direct help request from personnel node"),
    "presence": ("P", "possible presence cue (PIR); not a vital sign; absence cannot exclude a person"),
    "personnel_accounting": ("P", "personnel accounting report"),
    "asset_status": ("F", "asset status report (available/unavailable/unknown) with capacity interval"),
    "link_loss": ("U", "link loss: current evidence from source becomes unknown"),
    "link_restored": ("U", "link restored: delayed records enter history, not current window"),
    "buffer_eviction": ("U", "buffer eviction: observations lost"),
    "external_strike_report": ("SITE", "externally reported strike (authoritative external source)"),
    "air_raid_alert": ("SITE", "air-raid alert (authoritative external source)"),
    "air_raid_all_clear": ("SITE", "air-raid all-clear (authoritative external source)"),
}

SEMANTICS_UK = {
    "impact_excursion": "відхилення каналу прискорення (некалібровано; не міра руйнування)",
    "tilt_change": "зміна орієнтації вузла (структурне значення потребує перевіреного кріплення)",
    "pressure_transient": "перехідний процес тиску (не оцінка вибуху)",
    "loud_sound": "акустичний перехідний сигнал (не класифікація вибуху)",
    "possible_impact_local": "можливий локальний удар — НЕПІДТВЕРДЖЕНА складена ознака, не атрибуція удару",
    "structural_assessment": "висновок кваліфікованого експерта щодо конструкцій",
    "gas_channel_alarm": "спрацювання некаліброваного газового каналу (не концентрація, не ідентифікація)",
    "sos": "прямий запит допомоги (SOS)",
    "sos_reset": "скидання SOS оператором (не доказ надання допомоги)",
    "help_request": "запит допомоги з персонального вузла",
    "presence": "можлива ознака присутності (PIR) — не ознака життя",
    "personnel_accounting": "звіт про облік персоналу",
    "asset_status": "стан активу",
    "link_loss": "втрата зв'язку — поточні дані джерела невідомі",
    "link_restored": "зв'язок відновлено — затримані записи лише в історію",
    "buffer_eviction": "витіснення буфера — частину спостережень втрачено",
    "external_strike_report": "повідомлення про удар від уповноваженого зовнішнього джерела",
    "air_raid_alert": "повітряна тривога",
    "air_raid_all_clear": "відбій повітряної тривоги",
}

FRESHNESS_KEY = {
    "M": "mechanical_excursion", "H": "hazard_alarm", "P": "responder_report", "F": "asset_status",
}


@dataclass
class Assertion:
    assertion_id: str
    layer: str
    kind: str
    zone_id: Optional[str]
    site_id: Optional[str]
    semantics: str
    value: Any
    unit: Optional[str]
    source_class: Optional[str]
    source_id: Optional[str]
    observed_at: Optional[str]
    reported_at: Optional[str]
    time_uncertainty_s: Optional[float]
    quality: Optional[float]
    provenance: Dict[str, Any]
    event_ids: List[str]
    verification: str                 # unverified | instrument_uncalibrated | qualified | authoritative | report
    status: str = "current"           # current | stale | superseded | resolved
    version: int = 1
    supersedes: Optional[str] = None
    age_s: Optional[float] = None
    valid_until: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    ack_state: Optional[str] = None
    level: Optional[int] = None
    rule_version: Optional[Any] = None

    def to_dict(self):
        return asdict(self)

    @property
    def current(self) -> bool:
        return self.status == "current"


@dataclass
class ZoneState:
    zone_id: str
    site_id: Optional[str]
    name: str
    M: List[Assertion] = field(default_factory=list)
    H: List[Assertion] = field(default_factory=list)
    P: List[Assertion] = field(default_factory=list)
    F: List[Assertion] = field(default_factory=list)
    U: List[Assertion] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def layer(self, name: str) -> List[Assertion]:
        return getattr(self, name)

    def to_dict(self):
        return {"zone_id": self.zone_id, "site_id": self.site_id, "name": self.name,
                **{L: [a.to_dict() for a in getattr(self, L)] for L in LAYERS},
                "summary": self.summary}


@dataclass
class IncidentState:
    as_of: str
    incident_id: str
    zones: Dict[str, ZoneState]
    site_context: List[Assertion]
    rejected_attributions: List[Assertion]
    packets: List[dict]
    timing: List[dict]
    strike_statement_uk: str
    strike_statement_en: str

    def to_dict(self):
        return {"as_of": self.as_of, "incident_id": self.incident_id,
                "zones": {z: s.to_dict() for z, s in self.zones.items()},
                "site_context": [a.to_dict() for a in self.site_context],
                "rejected_attributions": [a.to_dict() for a in self.rejected_attributions],
                "packets": self.packets, "timing": self.timing,
                "strike_statement_uk": self.strike_statement_uk,
                "strike_statement_en": self.strike_statement_en}

    def zone_flags(self, zone_id: str) -> Dict[str, bool]:
        z = self.zones.get(zone_id)
        if z is None:
            return {}
        return z.summary.get("flags", {})


# ---------------------------------------------------------------------------
# Timing, Eq. (7)
# ---------------------------------------------------------------------------

def delay(t_e: Optional[str], t_x: Optional[str], uncertainty_s: Optional[float],
          clock_qualified: bool = True) -> Dict[str, Any]:
    """t_x - t_e with interval / unqualified handling (Sec. 3.8.2)."""
    te = parse_ts(t_e)
    tx = parse_ts(t_x)
    if tx is None:
        return {"status": "not_recorded", "value_s": None, "interval_s": None}
    if te is None or uncertainty_s is None or not clock_qualified:
        return {"status": "unqualified", "value_s": None, "interval_s": None,
                "reason": "event time not independently established or clocks not reconciled"}
    d = (tx - te).total_seconds()
    if uncertainty_s <= 0:
        return {"status": "point", "value_s": d, "interval_s": None}
    return {"status": "interval", "value_s": None, "interval_s": [d - uncertainty_s, d + uncertainty_s]}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _verification(e: Mapping) -> str:
    sc = e.get("source_class")
    et = e.get("event_type")
    if e.get("_unqualified_source"):
        return "unqualified_source"
    if sc == "authoritative_external_alert":
        return "authoritative"
    if et == "structural_assessment":
        prov = e.get("provenance") or {}
        if prov.get("assessor") and sc in ("responder_report", "operator_report"):
            return "qualified"
        return "unqualified_assessment"
    if et == "gas_channel_alarm":
        return "instrument_uncalibrated"
    if sc in ("responder_report", "operator_report"):
        return "report"
    return "unverified"


def build_incident_state(ds: Dataset, as_of: datetime, policy: Mapping,
                         first_display: Optional[Dict[str, str]] = None) -> IncidentState:
    fr = policy.get("freshness_s", {})
    first_display = first_display if first_display is not None else {}
    incident_id = "INC-" + str(ds.scenario_id)
    zones: Dict[str, ZoneState] = {}
    for zid, z in sorted(ds.zones.items()):
        zones[zid] = ZoneState(zid, z.get("site_id"), z.get("name", zid))
    site_ctx: List[Assertion] = []
    rejected: List[Assertion] = []

    def ensure_zone(zid: Optional[str], site: Optional[str]) -> Optional[ZoneState]:
        if not zid:
            return None
        if zid not in zones:
            zones[zid] = ZoneState(zid, site, zid)
            zones[zid].U.append(_meta_assertion(zid, site, "unrostered_zone",
                                                "zone not in roster: reported evidence kept, no roster denominator", as_of))
        return zones[zid]

    # ---- events -> assertions --------------------------------------------
    events = [e for e in ds.events if (parse_ts(e.get("reported_at")) or parse_ts(e.get("observed_at")) or as_of) <= as_of]
    impact_times = [parse_ts(e.get("observed_at")) for e in events if e.get("event_type") == "impact_excursion"]
    impact_times = [t for t in impact_times if t]
    for e in events:
        et = e.get("event_type")
        layer, sem = SEMANTICS.get(et, ("U", f"unrecognised event type '{et}' retained for review"))
        obs = parse_ts(e.get("observed_at"))
        if et == "loud_sound" and obs and not any(abs((obs - t).total_seconds()) <= 5 for t in impact_times):
            layer, sem = "P", "acoustic activity: possible presence cue only; not a vital sign"
        prov = e.get("provenance") or {}
        a = Assertion(
            assertion_id=f"A-{e.get('event_id')}", layer=layer, kind=et if layer != "P" or et != "loud_sound" else "acoustic_presence_cue",
            zone_id=e.get("zone_id"), site_id=e.get("site_id"), semantics=sem,
            value=e.get("value"), unit=e.get("unit"), source_class=e.get("source_class"),
            source_id=e.get("device_id"), observed_at=e.get("observed_at"), reported_at=e.get("reported_at"),
            time_uncertainty_s=e.get("time_uncertainty_s"), quality=e.get("quality"), provenance=prov,
            event_ids=[e.get("event_id")], verification=_verification(e), ack_state=e.get("ack_state"),
            level=e.get("level"), rule_version=e.get("rule_version"),
            valid_until=prov.get("valid_until"))
        if e.get("time_uncertainty_s") is None:
            a.notes.append("time uncertainty unknown: delays unqualified")
        a.age_s = (as_of - obs).total_seconds() if obs else None
        if layer == "SITE":
            if a.verification != "authoritative":
                a.status = "rejected_as_attribution"
                a.notes.append("strike/alert claims accepted only from authoritative_external_alert")
                rejected.append(a)
                z = ensure_zone(a.zone_id, a.site_id)
                if z:
                    z.U.append(_derived(a, "U", "non_authoritative_attribution_claim",
                                        "attribution claim from non-authoritative source; not used"))
            else:
                site_ctx.append(a)
            continue
        if a.verification == "unqualified_source":
            a.notes.append("source class not recognised: shown, not used for current state")
        z = ensure_zone(a.zone_id, a.site_id)
        if z is None:
            # site-level operational record without zone
            a.notes.append("no zone association")
            site_ctx.append(a)
            continue
        z.layer(layer).append(a)

    # ---- versioning / supersession ----------------------------------------
    for z in zones.values():
        _supersede(z.M, key=lambda a: (a.kind, a.zone_id) if a.kind == "structural_assessment" else None)
        _supersede(z.F, key=lambda a: (a.kind, (a.provenance or {}).get("asset_id") or a.source_id))
    # personnel accounting is versioned per worker across zones (people move)
    _supersede([a for z in zones.values() for a in z.P],
               key=lambda a: (a.kind, (a.provenance or {}).get("worker")) if a.kind == "personnel_accounting" else None)

    # ---- freshness ----------------------------------------------------------
    for z in zones.values():
        for L in ("M", "H", "P", "F"):
            for a in z.layer(L):
                if a.status != "current":
                    continue
                vu = parse_ts(a.valid_until)
                if vu is not None:
                    if as_of > vu:
                        a.status = "stale"
                        a.notes.append("validity period expired: history only")
                    continue
                horizon = _horizon(a, fr)
                if a.age_s is not None and horizon is not None and a.age_s > horizon:
                    a.status = "stale"
                    a.notes.append(f"older than freshness horizon {horizon}s: history only, no current authority")
    for a in site_ctx:
        if a.kind == "air_raid_alert":
            later = [b for b in site_ctx if b.kind == "air_raid_all_clear" and (b.observed_at or "") > (a.observed_at or "")]
            if later:
                a.status = "resolved"
        elif a.kind == "external_strike_report":
            h = fr.get("external_alert", 7200)
            if a.age_s is not None and a.age_s > h:
                a.status = "stale"

    # ---- SOS resolution -----------------------------------------------------
    for z in zones.values():
        resets = [a for a in z.P if a.kind == "sos_reset"]
        for a in z.P:
            if a.kind in ("sos", "help_request"):
                a.status = "current"   # assistance requests never age out silently
                for r in resets:
                    if r.source_id == a.source_id and (r.observed_at or "") > (a.observed_at or ""):
                        a.notes.append(f"local reset recorded at {r.observed_at}; reset is not proof of assistance")
                if a.ack_state == "resolved":
                    a.status = "resolved"

    # ---- station nodes: current evidence, gaps, attachment ------------------
    last_station: Dict[str, dict] = {}
    pir_last: Dict[str, dict] = {}
    for r in ds.station:
        t = parse_ts(r.get("measured_at"))
        if t is None or t > as_of:
            continue
        prev = last_station.get(r.get("device_id"))
        if prev is None or (prev.get("measured_at") or "") < (r.get("measured_at") or ""):
            last_station[r.get("device_id")] = r
        if r.get("pir_presence") is True:
            pp = pir_last.get(r.get("device_id"))
            if pp is None or (pp.get("measured_at") or "") < (r.get("measured_at") or ""):
                pir_last[r.get("device_id")] = r
    gap_thr = fr.get("link_gap_threshold", 60)
    open_link_loss: Dict[str, Assertion] = {}
    for z in zones.values():
        for a in z.U:
            if a.kind == "link_loss":
                restored = [b for b in z.U if b.kind == "link_restored" and b.source_id == a.source_id
                            and (b.observed_at or "") > (a.observed_at or "")]
                if restored:
                    a.status = "resolved"
                    a.notes.append(f"link restored at {restored[0].observed_at}; gap interval retained")
                else:
                    open_link_loss[a.source_id or z.zone_id] = a
            elif a.kind == "link_restored":
                a.status = "resolved"
    for dev, zid in sorted(ds.station_zone.items()):
        z = zones.get(zid)
        if z is None:
            continue
        r = last_station.get(dev)
        t = parse_ts(r.get("measured_at")) if r else None
        rcv = parse_ts(r.get("received_at")) if r else None
        age = (as_of - t).total_seconds() if t else None
        current = age is not None and age <= fr.get("station_current", 60)
        z.summary.setdefault("station_nodes", {})[dev] = {
            "last_measured_at": fmt_ts(t), "age_s": age, "current": current,
            "attachment_verified": r.get("attachment_verified") if r else None,
            "gas_v": r.get("gas_v") if (r and current) else None,
            "pir_presence": r.get("pir_presence") if (r and current) else None,
            "last_known": {k: r.get(k) for k in ("vib_peak_g", "tilt_deg", "pressure_hpa", "temp_c", "gas_v",
                                                  "sound_index", "pir_presence")} if r else None,
        }
        if not current:
            gap = Assertion(f"U-gap-{dev}", "U", "observation_gap", zid, z.site_id,
                            "no current stationary-node evidence: zone state UNKNOWN (not collapse, not casualty)",
                            None, None, "gateway", dev, fmt_ts(t), fmt_ts(as_of), None, None,
                            {"method": "silence/link-loss detection", "last_known_state": z.summary["station_nodes"][dev]["last_known"]},
                            [], "derived", age_s=age)
            ll = open_link_loss.get(dev) or open_link_loss.get(zid)
            if ll:
                gap.notes.append(f"link loss reported at {ll.observed_at}")
                gap.event_ids = list(ll.event_ids)
            elif age is None:
                gap.notes.append("no record received from this node")
            else:
                gap.notes.append(f"silence > {gap_thr}s")
            z.U.append(gap)
            # current evidence from a silent node becomes unknown; history is kept
            for a in z.H + z.P:
                if a.source_id == dev and a.status == "current" and a.kind not in ("sos", "help_request"):
                    a.status = "stale"
                    a.notes.append("source node silent / link lost: current evidence unknown, history retained")
        if r and r.get("attachment_verified") is False:
            z.U.append(Assertion(f"U-attach-{dev}", "U", "attachment_uncertain", zid, z.site_id,
                                 "node attachment uncertain: earlier structural interpretation withdrawn",
                                 None, None, "stationary_node", dev, r.get("measured_at"), r.get("received_at"),
                                 None, r.get("quality"), {}, [], "derived"))
            for a in z.M:
                if a.source_id == dev and a.kind != "structural_assessment":
                    a.notes.append("attachment uncertain: no structural interpretation")
        pr = pir_last.get(dev)
        pt = parse_ts(pr.get("measured_at")) if pr else None
        if pr and current and pt and (as_of - pt).total_seconds() <= fr.get("presence_cue", 300):
            z.P.append(Assertion(f"P-pir-{dev}", "P", "presence_cue", zid, z.site_id,
                                 SEMANTICS["presence"][1], True, None, "stationary_node", dev,
                                 pr.get("measured_at"), pr.get("received_at"), 0.5, pr.get("quality"),
                                 {"method": "PIR flag in station record"}, [],
                                 "unverified", age_s=(as_of - pt).total_seconds()))

    # personnel telemetry gaps (coverage) are summarised per zone
    last_phys: Dict[str, datetime] = {}
    for r in ds.physio:
        w = ds.device_map.get(r.get("device_id"), r.get("worker_pseudonym"))
        t = parse_ts(r.get("measured_at"))
        if w and t and t <= as_of and (w not in last_phys or t > last_phys[w]):
            last_phys[w] = t
    for zid, z in zones.items():
        roster = ds.zones.get(zid, {}).get("expected_workers", []) or []
        stale = [w for w in roster if w not in last_phys or (as_of - last_phys[w]).total_seconds() > fr.get("personnel_observation", 60)]
        z.summary["personnel_telemetry"] = {"expected": len(roster), "without_current_telemetry": len(stale)}
        if roster and stale:
            z.U.append(_meta_assertion(zid, z.site_id, "personnel_telemetry_gap",
                                       f"{len(stale)} of {len(roster)} expected workers without current telemetry; "
                                       "missing telemetry does not indicate injury or death", as_of))

    # ---- clock / contradictions ------------------------------------------------
    for z in zones.values():
        for L in ("M", "H", "P", "F"):
            for a in z.layer(L):
                if a.time_uncertainty_s is None and a.status == "current":
                    z.U.append(_derived(a, "U", "clock_uncertain", "observation time uncertainty unknown"))
        sa = [a for a in z.M if a.kind == "structural_assessment" and a.status == "current"]
        exc = [a for a in z.M if a.kind in ("impact_excursion", "possible_impact_local", "tilt_change") and a.status == "current"]
        for s in sa:
            if (s.value in ("no_restriction_observed", "no_visible_damage")) and any((x.observed_at or "") > (s.observed_at or "") for x in exc):
                z.U.append(_derived(s, "U", "contradictory_evidence",
                                    "new mechanical excursion after structural assessment: assessment requires review"))

    # ---- summaries -------------------------------------------------------------
    for z in zones.values():
        z.summary.update(_zone_summary(z))

    strike_uk, strike_en = _strike_statement(site_ctx, zones)
    for assoc in ds.manifest.get("incident_associations", []) or []:
        at = parse_ts(assoc.get("associated_at"))
        if at is None or at > as_of:
            continue
        if not any(a.event_ids and a.event_ids[0] == assoc.get("external_event_id") for a in site_ctx):
            continue
        strike_en += (f" Operational association {assoc.get('association_id')} by {assoc.get('associated_by')} at "
                      f"{assoc.get('associated_at')} links local events {', '.join(assoc.get('local_event_ids', []))} "
                      f"to the external report ({assoc.get('basis')}); local events remain unverified.")
        strike_uk += (f" Оперативна асоціація {assoc.get('association_id')} ({assoc.get('associated_by')}, "
                      f"{assoc.get('associated_at')}) пов'язує локальні події з зовнішнім повідомленням; "
                      "обидва ланцюги походження збережено, локальні події лишаються непідтвердженими.")
    packets = _packets(zones, site_ctx, incident_id, ds, as_of, first_display)
    timing = _timing(zones, events, first_display, as_of)
    return IncidentState(fmt_ts(as_of), incident_id, zones, site_ctx, rejected, packets, timing,
                         strike_uk, strike_en)


def _meta_assertion(zid, site, kind, sem, as_of) -> Assertion:
    return Assertion(f"U-{kind}-{zid}", "U", kind, zid, site, sem, None, None, "derived", None,
                     fmt_ts(as_of), fmt_ts(as_of), 0.0, None, {"method": "agent derivation"}, [], "derived")


def _derived(a: Assertion, layer: str, kind: str, sem: str) -> Assertion:
    return Assertion(f"{layer}-{kind}-{a.assertion_id}", layer, kind, a.zone_id, a.site_id, sem, None, None,
                     "derived", a.source_id, a.observed_at, a.reported_at, a.time_uncertainty_s, None,
                     {"derived_from": a.assertion_id}, list(a.event_ids), "derived")


def _horizon(a: Assertion, fr: Mapping) -> Optional[float]:
    if a.layer == "P":
        if a.kind in ("presence_cue", "presence", "acoustic_presence_cue"):
            return fr.get("presence_cue", 300)
        if a.source_class == "operator_report":
            return fr.get("operator_report", 1800)
        return fr.get("responder_report", 1800)
    if a.layer == "F":
        return fr.get("asset_status", 1800)
    if a.layer == "H":
        return fr.get("hazard_alarm", 600)
    if a.layer == "M":
        if a.kind == "structural_assessment":
            return None   # governed by valid_until
        return fr.get("mechanical_excursion", 1800)
    return None


def _supersede(items: List[Assertion], key) -> None:
    groups: Dict[Any, List[Assertion]] = {}
    for a in items:
        k = key(a)
        if k is None:
            continue
        groups.setdefault(k, []).append(a)
    for k, g in groups.items():
        g.sort(key=lambda a: (a.observed_at or "", a.reported_at or ""))
        for i, a in enumerate(g):
            a.version = i + 1
            if i > 0:
                a.supersedes = g[i - 1].assertion_id
            if i < len(g) - 1:
                a.status = "superseded"
                a.notes.append(f"superseded by {g[i + 1].assertion_id}")


def _zone_summary(z: ZoneState) -> Dict[str, Any]:
    cur = lambda L: [a for a in z.layer(L) if a.status == "current"]
    hist = lambda L: [a for a in z.layer(L)]
    sa = [a for a in z.M if a.kind == "structural_assessment" and a.status == "current" and a.verification == "qualified"]
    if sa:
        s = sa[-1]
        structural = {"state": s.value, "assessor": s.provenance.get("assessor"), "method": s.provenance.get("method"),
                      "scope": s.provenance.get("scope"), "valid_until": s.valid_until, "assertion_id": s.assertion_id}
    else:
        structural = {"state": "unknown", "assessor": None,
                      "note": "no current qualified structural assessment (no automated building clearance)"}
    mech_any = [a for a in hist("M") if a.kind in ("impact_excursion", "possible_impact_local", "tilt_change", "pressure_transient")]
    composite = [a for a in hist("M") if a.kind == "possible_impact_local"]
    gas_cur = [a for a in cur("H") if a.kind == "gas_channel_alarm"]
    gas_hist = [a for a in hist("H") if a.kind == "gas_channel_alarm"]
    gaps = [a for a in z.U if a.kind == "observation_gap" and a.status == "current"]
    nodes = z.summary.get("station_nodes", {})
    station_current = any(v.get("current") for v in nodes.values()) if nodes else False
    if gas_cur:
        hazard = "instrument_alarm_uncalibrated_channel"
    elif gas_hist and not station_current:
        hazard = "unknown_after_alarm (observation gap)"
    elif gas_hist:
        hazard = "alarm_history_no_current_alarm (uncalibrated channel; not cleared)"
    elif not station_current:
        hazard = "unknown (no current hazard instrument evidence)"
    else:
        hazard = "no_alarm_from_uncalibrated_channel (not a clearance)"
    presence = [a for a in cur("P") if a.kind in ("presence_cue", "presence", "acoustic_presence_cue")]
    sos = [a for a in z.P if a.kind in ("sos", "help_request") and a.status == "current"]
    assets = [a for a in cur("F")]
    flags = {
        "impact_evidence": bool(mech_any),
        "possible_impact_local": bool(composite),
        "gas_evidence": bool(gas_hist),
        "gas_alarm_current": bool(gas_cur),
        "observation_gap": bool(gaps),
        "structural_unknown": structural["state"] == "unknown",
        "presence_cue_current": bool(presence),
        "assistance_request_open": bool(sos),
    }
    return {"structural": structural, "hazard_state": hazard, "flags": flags,
            "mechanical_observations": len(mech_any), "presence_cues_current": len(presence),
            "open_assistance_requests": len(sos), "asset_reports_current": len(assets),
            "observation_gaps_current": len(gaps)}


def _strike_statement(site_ctx: List[Assertion], zones: Dict[str, ZoneState]):
    ext = [a for a in site_ctx if a.kind == "external_strike_report" and a.verification == "authoritative"]
    loc = [a for z in zones.values() for a in z.M if a.kind == "possible_impact_local"]
    if ext:
        e = ext[-1]
        uk = (f"Уповноважене зовнішнє джерело ({(e.provenance or {}).get('source', 'зовнішнє джерело')}) "
              f"повідомило про удар (спостереження {e.observed_at}, повідомлено {e.reported_at}). ")
        en = (f"An authoritative external source reported a strike (observed {e.observed_at}, reported {e.reported_at}). ")
        if loc:
            uk += ("Локальні складені ознаки possible_impact_local залишаються НЕПІДТВЕРДЖЕНИМИ; "
                   "зв'язок між ними та зовнішнім повідомленням встановлюється лише оперативним звітом.")
            en += ("Local possible_impact_local composites remain UNVERIFIED; association with the external "
                   "report requires an operational report retaining both provenance chains.")
    elif loc:
        uk = ("Є лише локальні складені ознаки possible_impact_local (НЕПІДТВЕРДЖЕНО). "
              "Атрибуція удару відсутня: її може надати лише уповноважене зовнішнє джерело.")
        en = ("Only local possible_impact_local composites exist (UNVERIFIED). No strike attribution: "
              "attribution may come only from an authoritative external source.")
    else:
        uk = "Повідомлень про удар від уповноважених джерел немає; локальних складених ознак немає."
        en = "No authoritative strike report; no local composite cues."
    return uk, en


def _last_confirmed_personnel(z: ZoneState) -> Optional[dict]:
    rep = [a for a in z.P if a.kind == "personnel_accounting" and a.source_class == "responder_report"]
    if not rep:
        return None
    a = sorted(rep, key=lambda x: x.observed_at or "")[-1]
    return {"assertion_id": a.assertion_id, "observed_at": a.observed_at, "value": a.value,
            "worker": (a.provenance or {}).get("worker"), "status": a.status, "source_class": a.source_class}


def _packets(zones, site_ctx, incident_id, ds: Dataset, as_of, first_display) -> List[dict]:
    services_by_zone: Dict[str, List[str]] = {}
    for s in (ds.assets.get("services") or []):
        if s.get("zone_id"):
            services_by_zone.setdefault(s["zone_id"], []).append(s.get("service_id"))
    out = []
    for z in zones.values():
        for L in LAYERS:
            for a in z.layer(L):
                if not a.event_ids and a.kind not in ("observation_gap", "presence_cue"):
                    continue
                pid = "PKT-" + sha256_obj([incident_id, a.assertion_id])[:12]
                first_display.setdefault(a.assertion_id, fmt_ts(as_of))
                out.append({
                    "packet_id": pid, "incident_id": incident_id, "zone_id": z.zone_id, "site_id": z.site_id,
                    "assertion_id": a.assertion_id, "layer": L, "version": a.version, "supersedes": a.supersedes,
                    "observed_at": a.observed_at, "reported_at": a.reported_at,
                    "first_displayed_at": first_display[a.assertion_id],
                    "time_uncertainty_s": a.time_uncertainty_s, "source_class": a.source_class,
                    "source_id": a.source_id, "event_semantics": a.semantics,
                    "event_semantics_uk": SEMANTICS_UK.get(a.kind, a.semantics),
                    "values": [{"name": a.kind, "value": a.value, "unit": a.unit}],
                    "quality": a.quality, "quality_reasons": list(a.notes),
                    "configuration": {"rule_version": a.rule_version,
                                      "calibration_id": (a.provenance or {}).get("calibration_id", "uncalibrated"),
                                      "method": (a.provenance or {}).get("method")},
                    "last_confirmed_personnel": _last_confirmed_personnel(z),
                    "operational_dependencies": sorted(services_by_zone.get(z.zone_id, [])),
                    "ack_state": a.ack_state or "unacknowledged",
                    "ack_note": "acknowledgement means received/reviewed by a responsible role; not proof that a rescue action occurred",
                    "status": a.status, "verification": a.verification, "age_s": a.age_s,
                })
    for a in site_ctx:
        pid = "PKT-" + sha256_obj([incident_id, a.assertion_id])[:12]
        first_display.setdefault(a.assertion_id, fmt_ts(as_of))
        out.append({"packet_id": pid, "incident_id": incident_id, "zone_id": a.zone_id, "site_id": a.site_id,
                    "assertion_id": a.assertion_id, "layer": "SITE", "version": a.version, "supersedes": None,
                    "observed_at": a.observed_at, "reported_at": a.reported_at,
                    "first_displayed_at": first_display[a.assertion_id],
                    "time_uncertainty_s": a.time_uncertainty_s, "source_class": a.source_class,
                    "source_id": a.source_id, "event_semantics": a.semantics,
                    "event_semantics_uk": SEMANTICS_UK.get(a.kind, a.semantics),
                    "values": [{"name": a.kind, "value": a.value, "unit": a.unit}],
                    "quality": a.quality, "quality_reasons": list(a.notes), "configuration": {},
                    "last_confirmed_personnel": None, "operational_dependencies": [],
                    "ack_state": a.ack_state or "unacknowledged", "status": a.status,
                    "verification": a.verification, "age_s": a.age_s})
    out.sort(key=lambda p: (p["observed_at"] or "", p["packet_id"]))
    return out


def _timing(zones, events, first_display, as_of) -> List[dict]:
    """Eq. (7) for primary episodes: SOS / help requests and possible_impact_local composites."""
    actions: Dict[str, str] = {}
    for e in events:
        prov = e.get("provenance") or {}
        if prov.get("method") == "response_action_start" and prov.get("related_event"):
            rel = prov["related_event"]
            if rel not in actions or (e.get("observed_at") or "") < actions[rel]:
                actions[rel] = e.get("observed_at")
    rows = []
    for e in events:
        if e.get("event_type") not in ("sos", "help_request", "possible_impact_local", "gas_channel_alarm"):
            continue
        aid = f"A-{e.get('event_id')}"
        tp = first_display.get(aid) or fmt_ts(as_of)
        clock_ok = (e.get("provenance") or {}).get("clock_qualified", True)
        u = e.get("time_uncertainty_s")
        rows.append({"event_id": e.get("event_id"), "event_type": e.get("event_type"), "zone_id": e.get("zone_id"),
                     "t_e": e.get("observed_at"), "time_uncertainty_s": u, "t_p": tp,
                     "t_a": actions.get(e.get("event_id")),
                     "T_report": delay(e.get("observed_at"), tp, u, clock_ok),
                     "T_action": delay(e.get("observed_at"), actions.get(e.get("event_id")), u, clock_ok),
                     "note": "t_p is the first incident-packet display time by this agent; not an end-to-end transport measurement"})
    return rows
