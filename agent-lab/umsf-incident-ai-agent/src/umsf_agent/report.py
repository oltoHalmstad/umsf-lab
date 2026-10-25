"""Deterministic outputs: Ukrainian briefing, JSON decision packages, Markdown
report and a single-file static HTML dashboard (inline SVG, no external deps)."""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

from . import __version__
from .continuity import fig14_table
from .util import dumps, fmt_ts, parse_ts

CATEGORY_UK = {
    "known": "враховані (підтвердження рятувальників або звірка координації)",
    "assistance_requested": "запит допомоги",
    "observed_not_location_confirmed": "є свіжа телеметрія пристрою (місце не підтверджено)",
    "unaccounted": "не враховані (місцеперебування не встановлено)",
    "unresolved": "нерозв'язані записи",
}
STATE_UK = {
    "no_configured_deviation_detected_under_adequate_monitoring": "налаштованих відхилень не виявлено (НЕ означає безпеку)",
    "individual_review_indicated": "показано індивідуальний перегляд",
    "possible_group_event": "можлива групова подія",
    "insufficient_monitoring_evidence": "недостатньо даних моніторингу",
}
STATUS_UK = {"OPTIMAL": "оптимальний розв'язок", "INFEASIBLE": "НЕЗДІЙСНЕННО"}
SYN_BANNER_UK = "СИНТЕТИЧНІ ДАНІ — сконструйований сценарій; не реальний об'єкт, люди, атака чи виміряна фізіологія"


def kyiv(ts: Optional[str]) -> str:
    """Europe/Kyiv display time (UTC is stored)."""
    dt = parse_ts(ts)
    if dt is None:
        return "невідомо"
    try:
        from zoneinfo import ZoneInfo
        loc = dt.astimezone(ZoneInfo("Europe/Kyiv"))
        return loc.strftime("%H:%M:%S") + " (Київ)"
    except Exception:  # tzdata missing: fixed-offset fallback, labelled
        loc = dt.astimezone(timezone(timedelta(hours=3)))
        return loc.strftime("%H:%M:%S") + " (UTC+3)"


def _age(s: Optional[float]) -> str:
    if s is None:
        return "вік невідомий"
    s = int(round(s))
    if s < 120:
        return f"{s} с тому"
    return f"{s // 60} хв тому"


def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}%".replace(".", ",")


# ---------------------------------------------------------------------------
# Deterministic Ukrainian briefing
# ---------------------------------------------------------------------------

def deterministic_briefing(res: Mapping, packages: List[Mapping], auto_approve: bool = False) -> str:
    inc, resc, cont, rec, phys = res["incident"], res["rescue"], res["continuity"]["result"], res["recovery"], res["physiology"]
    L: List[str] = []
    L.append("# Оперативна довідка для керівника реагування")
    L.append("")
    L.append("_Детерміновано згенерований текст (без мовної моделі). Усі висновки є пропозиціями і потребують затвердження._")
    L.append("")
    if res.get("data_origin") != "measured":
        L.append(f"> **{SYN_BANNER_UK}** (data_origin = `{res.get('data_origin')}`)")
        L.append("")
    if auto_approve:
        L.append("> **УВАГА: запуск з `--auto-approve-for-simulation`. Позначки «затверджено» є імітацією, а НЕ рішенням людини.**")
        L.append("")
    L.append(f"- Час стану: {res['as_of']} UTC = {kyiv(res['as_of'])}")
    L.append(f"- Інцидент: `{inc['incident_id']}`; SHA-256 вхідних даних: `{res['input_sha256'][:16]}…`")
    L.append("")
    L.append("## 1. Зовнішні сповіщення та атрибуція")
    for a in inc["site_context"]:
        if a["kind"] in ("air_raid_alert", "air_raid_all_clear", "external_strike_report"):
            st = {"current": "чинне", "resolved": "завершено", "stale": "застаріле"}.get(a["status"], a["status"])
            L.append(f"- {a['site_id']}: {a['kind']} — {st}; джерело: {(a.get('provenance') or {}).get('source', a['source_class'])}; "
                     f"спостереження {kyiv(a['observed_at'])}, повідомлено {kyiv(a['reported_at'])}")
    L.append(f"- {inc['strike_statement_uk']}")
    for a in inc["rejected_attributions"]:
        L.append(f"- Відхилено як атрибуцію: `{a['assertion_id']}` від `{a['source_class']}` "
                 f"({(a.get('provenance') or {}).get('source', '')}) — не є уповноваженим джерелом.")
    L.append("")
    L.append("## 2. Термінові запити допомоги (без групових порогів)")
    reqs = [(p, r) for p in resc["personnel"] for r in p["assistance_requests"]]
    st_sos = [t for t in resc["tasks"] if t["kind"] == "assist_sos" and t["subject"].get("device")]
    if not reqs and not st_sos:
        L.append("- Відкритих запитів немає.")
    pk_age = {p["assertion_id"]: p.get("age_s") for p in inc["packets"]}
    for p, r in reqs:
        L.append(f"- **{r['event_type'].upper()}** від `{p['worker']}`, зона {r.get('zone_id') or 'невідома'}, "
                 f"{_age(pk_age.get('A-' + r['event_id']))}; стан підтвердження: {r.get('ack_state')}; "
                 f"останній підтверджений контекст: {p['last_confirmed_location'].get('zone_id')} "
                 f"({p['last_confirmed_location'].get('basis')}).")
    for t in st_sos:
        L.append(f"- **SOS** зі стаціонарної кнопки `{t['subject']['device']}`, зона {t['zone_id']} — особа невідома; "
                 f"{_age(pk_age.get('A-' + str(t['subject'].get('request_event'))))}.")
    L.append("")
    L.append("## 3. Облік персоналу (звірка зі списком)")
    for k, v in sorted(resc["personnel_counts"].items()):
        L.append(f"- {CATEGORY_UK.get(k, k)}: {v}")
    for p in resc["personnel"]:
        if p["category"] in ("unaccounted", "unresolved"):
            loc = p["last_confirmed_location"]
            L.append(f"  - `{p['worker']}`: {CATEGORY_UK[p['category']]}; останнє підтверджене місце {loc.get('zone_id')} "
                     f"({loc.get('basis')}, {kyiv(loc.get('at'))}). Відсутність телеметрії не свідчить про травму чи загибель.")
    L.append("")
    L.append("## 4. Стан зон S_z = (M, H, P, F, U)")
    L.append("| Зона | Конструкції | Небезпеки | Прогалини спостереження | Ознаки присутності |")
    L.append("|---|---|---|---|---|")
    for zid, z in inc["zones"].items():
        s = z["summary"]
        st = s["structural"]
        stxt = "невідомо" if st["state"] == "unknown" else f"{st['state']} (експерт {st.get('assessor')}, до {kyiv(st.get('valid_until'))})"
        L.append(f"| {zid} {z['name']} | {stxt} | {s['hazard_state']} | {s['observation_gaps_current']} | "
                 f"{s['presence_cues_current']} (можливі ознаки, не ознаки життя) |")
    L.append("")
    L.append("## 5. Фізіологічна групова оцінка (лише агреговано)")
    for zid, z in phys["zones"].items():
        g = z["decision"]["group"]
        L.append(f"- {zid}: {z['decision']['label_uk']} — дійсні {g['n']}/{g['N']} (покриття {_pct(g['C_pct'])}), "
                 f"стійкі прапорці {g['m']} (частка {_pct(g['p_pct'])}). {z['feasibility']['note']}")
    L.append("- Групове попередження — це запит на розслідування, а не діагноз чи ідентифікація речовини.")
    L.append("")
    L.append("## 6. Рятувальна логістика — пропозиція розподілу (рівняння 8–9)")
    for a in resc["assignments"]:
        L.append(f"- {a['team_id']} → {a['task_id']} (зона {a['zone_id']}, {'термінове' if a['urgent'] else 'нетермінове'}, "
                 f"пріоритет {a['priority']}, оцінка часу ≈ {a['delta_s'] // 60} хв — кваліфікована оцінка, не маршрут)")
    for u in resc["unassigned"]:
        L.append(f"- **НЕ ПРИЗНАЧЕНО**{' (ТЕРМІНОВЕ)' if u['urgent'] else ''}: {u['task_id']} — " + "; ".join(u["limiting_constraints"]))
    if resc["active_limiting_constraints"]:
        L.append("- Активні обмеження: " + "; ".join(resc["active_limiting_constraints"]))
    o = resc["objective"]
    L.append(f"- Ціль (лексикографічно): термінових призначено {o['urgent_assigned']}, сумарний пріоритет {o['total_priority']}, "
             f"сумарний час {o['total_estimated_time_s'] // 60} хв.")
    L.append("")
    L.append("## 7. Безперервність сервісів (рівняння 10–11)")
    L.append(f"- Статус: {STATUS_UK.get(cont['status'], cont['status'])}.")
    if cont["status"] == "OPTIMAL":
        on = [k for k, v in cont["y"].items() if v]
        off = [k for k, v in cont["y"].items() if not v]
        L.append(f"- Підтримуються: {', '.join(on)}; не підтримуються: {', '.join(off) or '—'}; Q = {_pct(cont['Q_pct'])} "
                 "(зважене покриття сервісів, не частка врятованих людей).")
        L.append(f"- Обмежувальні ресурси: {', '.join(cont['binding_resources']) or '—'}; недопустимі/невідомі: "
                 f"{', '.join(cont['excluded_inadmissible']) or '—'}.")
    else:
        for r in cont["infeasibility_reasons"]:
            L.append(f"- Причина: {r}")
        L.append("- Обмеження безпеки життя НЕ послаблено. Варіанти для розгляду: " + "; ".join(cont["options_for_review"]))
    L.append("")
    L.append("## 8. Ліквідація наслідків — кандидатний графік")
    for t in rec["tasks"]:
        if t["status"] == "scheduled_candidate":
            L.append(f"- {kyiv(t['start'])}–{kyiv(t['finish'])}: {t['title_uk']} [{t['zone_id']}], бригада {t['crew']}"
                     + (" — критичний шлях" if t["critical"] else ""))
    for t in rec["blocked"]:
        L.append(f"- **ЗАБЛОКОВАНО**: {t['title_uk']} [{t['zone_id']}] — " + "; ".join(t["blocked_reasons"]))
    for x in rec["excluded_actuation"]:
        L.append(f"- Поза межами сервісу (керування обладнанням): {x.get('service_id') or x.get('task_id')} — {x['reason']}")
    L.append("")
    L.append("## 9. Рішення, що очікують затвердження людиною (Таблиця 9)")
    for p in packages:
        auth = p.get("authorisation")
        st = "очікує" if not auth else f"{auth['decision']} ({auth['role']}, {auth['actor']}: {auth['reason']})"
        L.append(f"- `{p['package_id']}` — {p['title_uk']}; уповноважена роль: {', '.join(p['authorising_roles_uk'])}; статус: {st}")
    L.append("")
    L.append("## 10. Межі")
    L.append("- Арифметика, допустимість, сповіщення та плани детерміновані; система не керує обладнанням, не ставить діагнозів, "
             "не призначає категорій сортування, не обирає маршрутів входу.")
    L.append("- Відсутні дані = невідомо, ніколи не «норма». Акустичні/PIR-сигнали — лише можливі ознаки присутності.")
    L.append("- Коефіцієнти не є ймовірностями виживання; система не валідована на реальних рятувальних операціях.")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# Markdown technical report
# ---------------------------------------------------------------------------

def markdown_report(res: Mapping, packages: List[Mapping], timeline: List[Mapping]) -> str:
    inc, resc, cont, rec = res["incident"], res["rescue"], res["continuity"]["result"], res["recovery"]
    L = ["# UMSF incident AI agent — technical run report", "",
         f"Agent version {__version__}; scenario `{res['scenario_id']}`; data origin `{res['data_origin']}`; state at {res['as_of']}.", "",
         "## Inputs", "", "| file | SHA-256 |", "|---|---|"]
    for k, v in sorted(res["file_sha256"].items()):
        L.append(f"| {k} | `{v}` |")
    d = res["dataset"]
    L += ["", f"Records: physio {d['physio_records']}, station {d['station_records']}, events {d['events']}; "
          f"duplicates dropped {d['duplicates_dropped']}; quarantined identities {d['quarantined_identities']}; "
          f"rejected lines {d['rejected_lines']}.", ""]
    L += ["## Decision packages", "", "| package | domain | authorising role | solver | status |", "|---|---|---|---|---|"]
    for p in packages:
        L.append(f"| `{p['package_id']}` | {p['domain']} | {', '.join(p['authorising_roles'])} | "
                 f"{p['solver'].get('method', '')[:60]} | {p['status']} |")
    L += ["", "## Rescue assignment (Eq. 8-9)", "", "| team | task | zone | urgent | p | delta (s) |", "|---|---|---|---|---|---|"]
    for a in resc["assignments"]:
        L.append(f"| {a['team_id']} | {a['task_id']} | {a['zone_id']} | {a['urgent']} | {a['priority']} | {a['delta_s']} |")
    L += ["", "Unassigned:", ""]
    for u in resc["unassigned"] or [{"task_id": "none", "limiting_constraints": []}]:
        L.append(f"- {u['task_id']}: {'; '.join(u['limiting_constraints'])}")
    L += ["", f"Objective: {resc['objective']}; solver: {resc['solver']['method']}", ""]
    L += ["## Service continuity (Eq. 10-11)", "", f"Status **{cont['status']}**, method {cont['method']}, Q = {cont['Q_pct']}", "",
          "| resource | capacity (lower bound) | used | unused |", "|---|---|---|---|"]
    for k, c in cont["resource_capacity"].items():
        L.append(f"| {k} | {c} | {cont['resource_use'].get(k, '—')} | {cont['unused'].get(k, '—')} |")
    L += ["", "| service | y |", "|---|---|"] + [f"| {k} | {v} |" for k, v in cont["y"].items()]
    L += ["", "## Recovery schedule", "", f"Makespan {rec['makespan_min']} min; critical path: {' -> '.join(rec['critical_path']) or '—'}", "",
          "| task | status | start | finish | crew | prerequisites | blocked |", "|---|---|---|---|---|---|---|"]
    for t in rec["tasks"]:
        L.append(f"| {t['task_id']} | {t['status']} | {t['start'] or '—'} | {t['finish'] or '—'} | {t['crew'] or '—'} | "
                 f"{', '.join(t['prerequisites']) or '—'} | {'; '.join(t['blocked_reasons']) or '—'} |")
    L += ["", "## Timing (Eq. 7)", "", "| event | type | T_report | T_action |", "|---|---|---|---|"]
    for t in inc["timing"]:
        L.append(f"| {t['event_id']} | {t['event_type']} | {_delay_txt(t['T_report'])} | {_delay_txt(t['T_action'])} |")
    if timeline:
        L += ["", "## Re-planning timeline", "", "| as_of | changed domains | open requests | unassigned urgent | continuity | Q |",
              "|---|---|---|---|---|---|"]
        for r in timeline:
            L.append(f"| {r['as_of']} | {', '.join(r['changed_domains']) or '(no change)'} | {r['open_assistance_requests']} | "
                     f"{r['unassigned_urgent']} | {r['continuity_status']} | {'' if r['Q_pct'] is None else round(r['Q_pct'], 2)} |")
    L += ["", "All plans are proposals. See docs/SAFETY_AND_ETHICS.md.", ""]
    return "\n".join(L)


def _delay_txt(d: Mapping) -> str:
    if d["status"] == "point":
        return f"{d['value_s']:.1f} s"
    if d["status"] == "interval":
        return f"[{d['interval_s'][0]:.1f}, {d['interval_s'][1]:.1f}] s"
    return d["status"]


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------

CSS = """
:root{color-scheme:light;--surface-0:#f4f3f0;--surface-1:#fcfcfb;--border:#dddcd6;--grid:#e6e5e0;
--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#77766f;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--neutral:#c9c8c1;
--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;
--border:#383835;--grid:#2c2c2a;--text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#9a9990;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--neutral:#4a4a46}}
:root[data-theme="dark"]{color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;--border:#383835;--grid:#2c2c2a;
--text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#9a9990;--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--neutral:#4a4a46}
*{box-sizing:border-box}body{margin:0;background:var(--surface-0);color:var(--text-primary);
font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:4px 0 2px}h2{font-size:16px;margin:0 0 10px}
.sub{color:var(--text-secondary);margin:0 0 12px}
.banner{border:1px solid var(--serious);border-left:6px solid var(--serious);background:var(--surface-1);padding:8px 12px;margin:10px 0;border-radius:6px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:14px;margin:12px 0;overflow-x:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.zone{border:1px solid var(--border);border-radius:8px;padding:10px;min-width:0}
.zone h3{margin:0 0 6px;font-size:14px}
.kv{display:flex;justify-content:space-between;gap:8px;font-size:12.5px;padding:2px 0;border-bottom:1px dashed var(--grid)}
.kv span:first-child{color:var(--text-secondary);flex:0 0 auto;white-space:nowrap}
.kv span:last-child{min-width:0;overflow-wrap:anywhere;text-align:right}
.chip{display:inline-flex;align-items:center;gap:4px;font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid var(--border);margin:2px 2px 0 0}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{text-align:left;padding:5px 6px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--text-secondary);font-weight:600}
.num{font-variant-numeric:tabular-nums;text-align:right}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.tile .v{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}.tile .l{color:var(--text-secondary);font-size:12px}
svg text{fill:var(--text-secondary);font-size:11px}svg .ink{fill:var(--text-primary)}
details summary{cursor:pointer;color:var(--text-secondary)}
.muted{color:var(--text-muted)}code{font-size:12px}
"""

ICON = {"critical": "▲", "serious": "◆", "warning": "●", "good": "✓", "unknown": "?"}


def _chip(level: str, label: str) -> str:
    color = {"critical": "var(--critical)", "serious": "var(--serious)", "warning": "var(--warning)",
             "good": "var(--good)", "unknown": "var(--neutral)"}[level]
    return f'<span class="chip"><span class="dot" style="background:{color}"></span>{ICON[level]} {html.escape(label)}</span>'


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def _zone_cards(res) -> str:
    inc, phys = res["incident"], res["physiology"]["zones"]
    out = []
    for zid, z in inc["zones"].items():
        s = z["summary"]
        f = s.get("flags", {})
        chips = []
        if f.get("assistance_request_open"):
            chips.append(_chip("critical", "відкритий запит допомоги"))
        if f.get("possible_impact_local"):
            chips.append(_chip("serious", "possible_impact_local (НЕПІДТВЕРДЖЕНО)"))
        if f.get("gas_alarm_current"):
            chips.append(_chip("serious", "газовий канал (некалібр.)"))
        elif f.get("gas_evidence"):
            chips.append(_chip("warning", "історія газового сигналу"))
        if f.get("observation_gap"):
            chips.append(_chip("unknown", "прогалина спостереження"))
        if f.get("presence_cue_current"):
            chips.append(_chip("warning", "можлива ознака присутності"))
        st = s["structural"]
        if st["state"] == "unknown":
            chips.append(_chip("unknown", "конструкції: невідомо"))
        else:
            chips.append(_chip("good", f"оцінка експерта: {st['state']}"))
        d = phys.get(zid, {}).get("decision", {})
        g = d.get("group", {})
        layers = " · ".join(f"{L}:{len(z[L])}" for L in ("M", "H", "P", "F", "U"))
        out.append(f"""<div class="zone"><h3>{_e(zid)} — {_e(z['name'])} <span class="muted">({_e(z['site_id'])})</span></h3>
<div>{''.join(chips)}</div>
<div class="kv"><span>Небезпеки (H)</span><span>{_e(s['hazard_state'])}</span></div>
<div class="kv"><span>Фізіол. група</span><span>{_e(d.get('label_uk', '—'))}</span></div>
<div class="kv"><span>Дійсні / список</span><span class="num">{_e(g.get('n'))} / {_e(g.get('N'))} ({_pct(g.get('C_pct'))})</span></div>
<div class="kv"><span>Записи S_z</span><span class="num">{layers}</span></div></div>""")
    return '<div class="grid">' + "".join(out) + "</div>"


def _bars(cont) -> str:
    rows = list(cont["resource_capacity"].items())
    if not rows:
        return "<p class='muted'>немає ресурсів</p>"
    W, rowh, left, right = 640, 34, 120, 110
    H = rowh * len(rows) + 24
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Використання ресурсів відносно нижньої межі">']
    for i, (k, cap) in enumerate(rows):
        used = cont["resource_use"].get(k, 0) or 0
        y = 10 + i * rowh
        span = W - left - right
        mx = max(cap, used, 1e-9)
        wcap = span * (cap / mx)
        wused = span * (min(used, cap) / mx) if cap else 0
        parts.append(f'<text x="0" y="{y + 15}" class="ink">{_e(k)}</text>')
        parts.append(f'<rect x="{left}" y="{y + 4}" width="{max(wcap, 1):.1f}" height="16" rx="4" fill="var(--neutral)">'
                     f'<title>{_e(k)}: межа {cap:g}</title></rect>')
        if wused > 0:
            parts.append(f'<rect x="{left}" y="{y + 4}" width="{wused:.1f}" height="16" rx="4" fill="var(--series-1)">'
                         f'<title>{_e(k)}: використано {used:g} з {cap:g}</title></rect>')
        parts.append(f'<text x="{left + span + 8}" y="{y + 16}">{used:g} / {cap:g}</text>')
    parts.append("</svg>")
    legend = ('<div class="muted" style="font-size:12px"><span class="dot" style="background:var(--series-1)"></span> використано '
              '&nbsp; <span class="dot" style="background:var(--neutral)"></span> обґрунтована нижня межа (невідомо = 0)</div>')
    return "".join(parts) + legend


def _gantt(rec, as_of: str) -> str:
    rows = [t for t in rec["tasks"] if t["status"] == "scheduled_candidate"]
    if not rows:
        return "<p class='muted'>немає запланованих завдань</p>"
    crews = sorted({t["crew"] for t in rows})
    colors = ["var(--series-1)", "var(--series-2)", "var(--series-3)"]
    cmap = {c: colors[i % 3] for i, c in enumerate(crews)}
    end = max(t["finish_offset_min"] for t in rows) or 1
    W, left, rowh = 760, 230, 26
    span = W - left - 20
    H = rowh * len(rows) + 40
    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Діаграма Ганта кандидатного графіка">']
    step = 30 if end > 120 else 15
    for m in range(0, int(end) + step, step):
        x = left + span * m / end
        if x > W - 10:
            break
        p.append(f'<line x1="{x:.1f}" y1="14" x2="{x:.1f}" y2="{H - 18}" stroke="var(--grid)"/>')
        p.append(f'<text x="{x:.1f}" y="{H - 4}" text-anchor="middle">+{m} хв</text>')
    for i, t in enumerate(rows):
        y = 18 + i * rowh
        x0 = left + span * t["start_offset_min"] / end
        w = max(2.0, span * (t["finish_offset_min"] - t["start_offset_min"]) / end - 2)
        p.append(f'<text x="0" y="{y + 13}" class="ink">{_e(t["kind"])} [{_e(t["zone_id"])}]</text>')
        stroke = ' stroke="var(--text-primary)" stroke-width="1.5"' if t["critical"] else ""
        p.append(f'<rect x="{x0:.1f}" y="{y}" width="{w:.1f}" height="17" rx="4" fill="{cmap[t["crew"]]}"{stroke}>'
                 f'<title>{_e(t["title_uk"])}: {_e(kyiv(t["start"]))}–{_e(kyiv(t["finish"]))}, бригада {_e(t["crew"])}'
                 f'{", критичний шлях" if t["critical"] else ""}</title></rect>')
    p.append("</svg>")
    leg = " &nbsp; ".join(f'<span class="dot" style="background:{cmap[c]}"></span> {_e(c)}' for c in crews)
    return "".join(p) + f'<div class="muted" style="font-size:12px">Бригади: {leg} &nbsp; (обведено — критичний шлях)</div>'


def _fig14() -> str:
    rows = fig14_table()
    W, H, l, b, t, r = 560, 220, 44, 30, 12, 12
    sx = lambda B: l + (W - l - r) * B / 12
    sy = lambda q: t + (H - t - b) * (1 - q / 100)
    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Рис. 14: Q залежно від ємності B">']
    p.append(f'<rect x="{sx(0):.1f}" y="{t}" width="{sx(3) - sx(0):.1f}" height="{H - t - b}" fill="var(--neutral)" opacity="0.35"/>')
    p.append(f'<text x="{(sx(0) + sx(3)) / 2:.1f}" y="{t + 14}" text-anchor="middle" class="ink">НЕЗДІЙСНЕННО</text>')
    for q in (0, 25, 50, 75, 100):
        p.append(f'<line x1="{l}" x2="{W - r}" y1="{sy(q):.1f}" y2="{sy(q):.1f}" stroke="var(--grid)"/>'
                 f'<text x="{l - 6}" y="{sy(q) + 4:.1f}" text-anchor="end">{q}%</text>')
    for B in range(0, 13):
        p.append(f'<text x="{sx(B):.1f}" y="{H - 10}" text-anchor="middle">{B}</text>')
    pts = [(row["B"], row["Q_pct"]) for row in rows if row["Q_pct"] is not None]
    path = " ".join(f"{'M' if i == 0 else 'L'}{sx(B):.1f},{sy(q):.1f}" for i, (B, q) in enumerate(pts))
    p.append(f'<path d="{path}" fill="none" stroke="var(--series-1)" stroke-width="2"/>')
    for row in rows:
        if row["Q_pct"] is None:
            continue
        p.append(f'<circle cx="{sx(row["B"]):.1f}" cy="{sy(row["Q_pct"]):.1f}" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2">'
                 f'<title>B = {row["B"]}: y = {tuple(row["y"])}, Q = {row["Q_pct"]}%</title></circle>')
    for B, lab in ((3, "68,75%"), (6, "93,75%"), (10, "100%")):
        q = next(r_["Q_pct"] for r_ in rows if r_["B"] == B)
        p.append(f'<text x="{sx(B) + 6:.1f}" y="{sy(q) + 16:.1f}" class="ink">{lab}</text>')
    p.append(f'<text x="{W / 2}" y="{H}" text-anchor="middle"></text></svg>')
    return "".join(p)


def _sparkline(timeline: List[Mapping]) -> str:
    if len(timeline) < 2:
        return ""
    vals = [r["unassigned_urgent"] for r in timeline]
    W, H, pad = 560, 70, 6
    mx = max(max(vals), 1)
    pts = []
    for i, v in enumerate(vals):
        x = pad + (W - 2 * pad) * i / (len(vals) - 1)
        y = H - pad - (H - 2 * pad - 12) * v / mx
        pts.append((x, y, v, timeline[i]["as_of"]))
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y, _, _) in enumerate(pts))
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="transparent"><title>{_e(kyiv(a))}: {v} термінових не призначено</title></circle>'
                   for x, y, v, a in pts)
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Неназначені термінові завдання в часі">'
            f'<path d="{path}" fill="none" stroke="var(--series-2)" stroke-width="2"/>{dots}'
            f'<text x="{pad}" y="12">макс. {mx}</text></svg>'
            '<div class="muted" style="font-size:12px">Кількість непризначених термінових завдань на кожному кроці перепланування</div>')


def dashboard_html(res: Mapping, packages: List[Mapping], timeline: List[Mapping], auto_approve: bool = False) -> str:
    resc, cont, rec = res["rescue"], res["continuity"]["result"], res["recovery"]
    open_req = sum(len(p["assistance_requests"]) for p in resc["personnel"]) + \
        sum(1 for t in resc["tasks"] if t["kind"] == "assist_sos" and t["subject"].get("device"))
    tiles = [
        (open_req, "відкритих запитів допомоги"),
        (len(resc["unassigned_urgent"]), "термінових не призначено"),
        (resc["personnel_counts"].get("unaccounted", 0) + resc["personnel_counts"].get("unresolved", 0), "не враховано / нерозв'язано"),
        (_pct(cont["Q_pct"]) if cont["status"] == "OPTIMAL" else "НЕЗДІЙСН.", "Q сервісів (зважене)"),
        (sum(1 for p in packages if not p.get("authorisation")), "рішень очікують затвердження"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="v">{_e(v)}</div><div class="l">{_e(l)}</div></div>' for v, l in tiles)
    asg = "".join(f"<tr><td>{_e(a['team_id'])}</td><td>{_e(a['task_id'])}</td><td>{_e(a['zone_id'])}</td>"
                  f"<td>{'так' if a['urgent'] else 'ні'}</td><td class='num'>{a['priority']}</td><td class='num'>{a['delta_s'] // 60}</td></tr>"
                  for a in resc["assignments"])
    una = "".join(f"<tr><td>{_e(u['task_id'])}</td><td>{'ТЕРМІНОВЕ' if u['urgent'] else '—'}</td><td>{_e('; '.join(u['limiting_constraints']))}</td></tr>"
                  for u in resc["unassigned"]) or "<tr><td colspan=3 class='muted'>немає</td></tr>"
    svc = "".join(f"<tr><td>{_e(k)}</td><td>{'підтримується' if v else 'ні'}</td></tr>" for k, v in cont["y"].items())
    pk = "".join(f"<tr><td><code>{_e(p['package_id'])}</code></td><td>{_e(p['title_uk'])}</td><td>{_e(', '.join(p['authorising_roles_uk']))}</td>"
                 f"<td>{_e(p['authorisation']['decision'] if p.get('authorisation') else 'очікує затвердження')}</td></tr>" for p in packages)
    blocked = "".join(f"<li>{_e(t['title_uk'])} [{_e(t['zone_id'])}]: {_e('; '.join(t['blocked_reasons']))}</li>" for t in rec["blocked"]) \
        or "<li class='muted'>немає</li>"
    infeas = "".join(f"<li>{_e(r)}</li>" for r in cont["infeasibility_reasons"])
    sim = ('<div class="banner"><strong>Імітація:</strong> позначки «затверджено» створені прапорцем '
           '<code>--auto-approve-for-simulation</code> і НЕ є рішеннями людини.</div>') if auto_approve else ""
    return f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UMSF Incident Dashboard</title><style>{CSS}</style></head>
<body><main>
<h1>Панель підтримки рішень — інцидент {_e(res['incident']['incident_id'])}</h1>
<p class="sub">Стан на {_e(res['as_of'])} UTC ({_e(kyiv(res['as_of']))}) · агент v{_e(__version__)} · вхідні дані SHA-256 <code>{_e(res['input_sha256'][:16])}…</code></p>
<div class="banner"><strong>{_e(SYN_BANNER_UK) if res.get('data_origin') != 'measured' else 'Виміряні дані'}</strong>.
Усі плани — ПРОПОЗИЦІЇ, що потребують затвердження уповноваженою роллю. Система не керує обладнанням, не ставить діагнозів і не обирає маршрутів входу.</div>
{sim}
<div class="tiles">{tiles_html}</div>
<div class="card"><h2>Атрибуція</h2><p>{_e(res['incident']['strike_statement_uk'])}</p></div>
<div class="card"><h2>Зони: S<sub>z</sub> = (M, H, P, F, U)</h2>{_zone_cards(res)}</div>
<div class="card"><h2>Рятувальна логістика — пропозиція призначень (рівн. 8–9)</h2>
<table><thead><tr><th>Ланка</th><th>Завдання</th><th>Зона</th><th>Термін.</th><th class="num">p</th><th class="num">δ, хв (оцінка)</th></tr></thead><tbody>{asg}</tbody></table>
<h2 style="margin-top:14px">Непризначені завдання та обмеження</h2>
<table><thead><tr><th>Завдання</th><th>Терміновість</th><th>Обмеження</th></tr></thead><tbody>{una}</tbody></table>
{_sparkline(timeline)}</div>
<div class="card"><h2>Безперервність сервісів — {_e(STATUS_UK.get(cont['status'], cont['status']))}</h2>
{_bars(cont) if cont['status'] == 'OPTIMAL' else '<ul>' + infeas + '</ul>'}
<table><thead><tr><th>Сервіс</th><th>y</th></tr></thead><tbody>{svc}</tbody></table>
<details><summary>Довідково: приклад розділу 4.9 (Таблиця 16, Рис. 14)</summary>{_fig14()}</details></div>
<div class="card"><h2>Ліквідація наслідків — кандидатний графік (Ганта)</h2>{_gantt(rec, res['as_of'])}
<h2 style="margin-top:14px">Заблоковані завдання / невирішені передумови</h2><ul>{blocked}</ul></div>
<div class="card"><h2>Рішення, що очікують затвердження (Таблиця 9)</h2>
<table><thead><tr><th>Пакет</th><th>Домен</th><th>Уповноважена роль</th><th>Статус</th></tr></thead><tbody>{pk}</tbody></table></div>
<p class="muted">Відсутні дані = невідомо. Акустичні/PIR-сигнали — лише можливі ознаки присутності. Коефіцієнти не є ймовірностями виживання.</p>
</main></body></html>
"""


def write_reports(out_dir: str, res: Mapping, packages: List[Mapping], timeline: List[Mapping],
                  llm_out: Optional[Mapping] = None, auto_approve: bool = False) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = {}

    def w(name, text):
        p = os.path.join(out_dir, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        paths[name] = p

    w("decision_packages.json", dumps({"as_of": res["as_of"], "auto_approve_for_simulation": auto_approve,
                                       "packages": packages}) + "\n")
    w("result.json", dumps(res) + "\n")
    w("incident_packets.json", dumps(res["incident"]["packets"]) + "\n")
    brief = deterministic_briefing(res, packages, auto_approve)
    w("briefing.md", brief)
    if llm_out is not None:
        txt = llm_out["text"]
        hdr = ("> **AI-generated summary — verify against deterministic outputs** (Згенеровано ШІ — перевіряйте за детермінованими результатами)\n\n"
               if llm_out["source"] == "llm" else
               f"> Мовна модель недоступна або її текст відхилено ({llm_out.get('fallback_reason')}); нижче — детермінована довідка.\n\n")
        w("ai_briefing.md", hdr + txt)
    w("report.md", markdown_report(res, packages, timeline))
    w("dashboard.html", dashboard_html(res, packages, timeline, auto_approve))
    if timeline:
        w("timeline.json", dumps(timeline) + "\n")
    return paths
