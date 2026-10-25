"""Assemble UMSF_AI_Agent_Lab.ipynb from notebook/umsf_ai_lab.py, the cell texts below and a payload built
from the release tree (solid tar.xz, Base85). Run from any directory: python scripts/build_notebook.py"""
from pathlib import Path
import base64, hashlib, io, json, lzma, tarfile, textwrap
import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

ROOT = Path(__file__).resolve().parents[1]


def build_payload() -> tuple[str, str, int]:
    inventory = json.loads((ROOT / 'provenance/source_sha256.json').read_text())
    files = [ROOT / name for name in inventory] + [ROOT / 'provenance/source_sha256.json']
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:xz', preset=9 | lzma.PRESET_EXTREME) as archive:
        for p in sorted(files, key=lambda p: p.relative_to(ROOT).as_posix()):
            info = tarfile.TarInfo(p.relative_to(ROOT).as_posix())
            info.size, info.mode, info.mtime = p.stat().st_size, 0o644, 1792022400  # 2026-10-15, deterministic
            with p.open('rb') as handle:
                archive.addfile(info, handle)
    blob = buffer.getvalue()
    return hashlib.sha256(blob).hexdigest(), '\n'.join(textwrap.wrap(base64.b85encode(blob).decode(), 120)), len(blob)


def md(text):
    return new_markdown_cell(textwrap.dedent(text).strip())


def code(text, **metadata):
    cell = new_code_cell(textwrap.dedent(text).strip())
    cell.metadata.update(metadata)
    return cell


HEAD = 'from umsf_ai_lab import *  # shared runtime from Section 0; every cell is self-sufficient after setup\n'


def analysis(text):
    return code(HEAD + textwrap.dedent(text).strip())


EXPLORER = r"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>UMSF Agent Explorer</title><style>body{font:16px system-ui;margin:30px auto;padding:20px;max-width:1050px;background:#f3f6fa;color:#183342}h1{color:#087e8b}.card{padding:20px;background:white;border-radius:12px;margin:18px 0}input{width:100%}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px;border-bottom:1px solid #ddd}.stats{display:flex;gap:25px;flex-wrap:wrap}.muted{color:#546774}</style><h1>UMSF Incident AI Agent Explorer</h1><p>Synthetic scenario · proposals only · no actuation · no external API</p><div class="card"><label for="time">Replay snapshot</label><input id="time" type="range" min="0" max="40" value="30"><h2 id="stamp"></h2><div class="stats" id="stats"></div></div><div class="card"><table><thead><tr><th>Zone</th><th>Eligible coverage</th><th>Group interpretation</th></tr></thead><tbody id="zones"></tbody></table></div><p class="muted">Q means weighted service coverage, not lives saved. Missing evidence never establishes safety. Plans require authorized human review.</p><script>const DATA=__DATA__;function render(){const r=DATA[Number(document.getElementById('time').value)];document.getElementById('stamp').textContent=r.time;document.getElementById('stats').innerHTML='<span>Continuity: <b>'+r.continuity+'</b></span><span>Q: <b>'+(r.q===null?'undefined':r.q.toFixed(2)+'%')+'</b></span><span>Assigned: <b>'+r.assigned+'/'+r.tasks+'</b></span><span>Unassigned urgent: <b>'+r.unassigned_urgent+'</b></span>';document.getElementById('zones').innerHTML=r.zones.map(z=>'<tr><td>'+z.zone+'</td><td>'+(z.coverage===null?'undefined':z.coverage.toFixed(1)+'%')+'</td><td>'+z.state+'</td></tr>').join('')}document.getElementById('time').addEventListener('input',render);render();</script></html>"""


def cells(payload_sha, payload_text, payload_bytes):
    lab_source = (ROOT / 'notebook/umsf_ai_lab.py').read_text()
    hidden = {'collapsed': True, 'jupyter': {'source_hidden': True}}
    return [
md("""
# UMSF Incident AI Agent Laboratory
### Evidence-aware assessment, rescue proposals and infrastructure recovery
**English · Self-contained Colab notebook · Companion version 1.2.0 · Original agent 1.0.0**

Upload this notebook to [Google Colab](https://colab.research.google.com/), select Python 3 on CPU and run all cells. It embeds the original agent, both synthetic scenarios and the companion P1 integration fixture. No API key, external dataset, paid service or device is required. Python plotting dependencies are installed only if missing. The computational core uses the standard library.

**Self-sufficient cells.** Section 0 writes a small verified runtime (`umsf_ai_lab.py`) next to the notebook. After it has run once, *every* analysis cell can be executed on its own, in any order, and again after **Runtime → Restart session**: each cell begins with `from umsf_ai_lab import *`, and the tests, checks and agent replays it needs are computed on first use and cached.

The agent is AI in the sense of observing, maintaining state, planning and proposing decisions. Its scores, matching, allocation and scheduling are deterministic. The optional language-model integration is not invoked. Every plan remains a **proposal**, and this notebook neither dispatches teams nor controls equipment.

All scenario records are **synthetic**. Physiological scores are deviations, not diagnoses; weighted service coverage is not people rescued; sensor silence is missing evidence; a local impact composite is not causal attribution. No operational rescue validation is claimed. The original localized source and examples are preserved for provenance; all new narrative, figures, tables and the standalone explorer are English.

**Learning route:** tests and ingestion → robust scoring and coverage → chronological incident replay → rescue matching → constrained continuity → recovery scheduling → proposal authority and audit → reproducible exports.
"""),
md(f"""
## 0. Setup — run once per runtime
Three cells prepare everything; nothing is downloaded except missing Python libraries.

1. **Embedded project** (collapsed): writes `umsf_ai_payload.py` – a {payload_bytes:,}-byte xz-compressed tar (Base85) with the original agent source, tests, both synthetic scenarios, the P1 fixture and the source inventory; SHA-256 `{payload_sha[:16]}…`.
2. **Runtime module** (collapsed): writes `umsf_ai_lab.py` – dependency check, payload/hash verification, plotting conventions and cached analysis states. Expand it to read the code.
3. **Start**: imports the runtime. It verifies the payload and all 77 source/fixture hashes and extracts the project once to `umsf_agent_runs/project/` (later imports reuse the verified copy).

If a cell later reports `No module named 'umsf_ai_lab'`, the runtime files were removed (for example after **Disconnect and delete runtime**): run these three cells again.
"""),
code(f'%%writefile umsf_ai_payload.py\n# Embedded UMSF agent project: xz-compressed tar, Base85 text. Generated by scripts/build_notebook.py.\n'
     f"PAYLOAD_SHA256 = '{payload_sha}'\nPAYLOAD = \"\"\"\n{payload_text}\n\"\"\"\n", tags=['embedded-payload'], **hidden),
code('%%writefile umsf_ai_lab.py\n' + lab_source, tags=['runtime-module'], **hidden),
code("""
import importlib, sys
if 'umsf_ai_lab' in sys.modules:       # re-running setup: reload a possibly edited runtime, clear caches
    importlib.reload(sys.modules['umsf_ai_lab'])
from umsf_ai_lab import *
status()
"""),
md("""
## 1. Setup and plotting conventions

Charts are computed from the supplied package or clearly labeled illustrative inputs. Source hashes distinguish preserved files from generated results. Each replay starts a fresh audit chain, so re-running is safe.
"""),
analysis("""
print(json.dumps(versions(), indent=2))
"""),
md("""
## 2. Run the original test suite

The supplied archive alone skips six tests because the P1 sibling dataset is absent. This notebook includes the P1 incident fixture from the earlier companion project, in the layout expected by the unchanged tests. The full suite must pass with zero skips. The tests include matching-versus-brute-force comparisons, constraint enforcement, ingestion, audit checks and offline language-model mocks; they do not establish real-world effectiveness.

*Optimization:* the ten test modules run as concurrent `unittest` processes, and the independent no-backup scenario replay (Section 19) starts in the background at the same time.
"""),
analysis("""
T = original_tests()
print(T.log[-250:])
counts=pd.Series(T.modules).value_counts().sort_values()
fig,ax=newfig(figsize=(10,6));counts.plot.barh(ax=ax,color=COLORS[0]);ax.set(xlabel='Passing test cases',title=f'Original test suite: {T.n_tests} tests, zero skips');save('01_tests')
"""),
md("""
## 3. Reproduce the supplied analytical checks

The package encodes reference values labeled Table 10 and Table 16 of its companion manuscript. We reproduce those supplied targets directly; the manuscript itself is not independently reviewed here. Forty-four checks compare actual and expected values.
"""),
analysis("""
P = paper_checks(); case_df = P.case_df
print(f'{len(P.paper)}/{len(P.paper)} supplied analytical checks passed.')
display(case_df)
fig,ax=newfig();case_df.set_index('case')[['coverage_pct','flagged_pct']].plot.bar(ax=ax,color=COLORS[:2])
ax.set(ylabel='Percent (different denominators)',title='Coverage and affected proportion must be read together');save('02_reference_cases')
"""),
md("""
## 4. Source inventory and ingestion

Record identity is used for deduplication. A conflicting payload under an existing identity quarantines both versions. The roster remains the population denominator, even if devices stop reporting. The supplied scenario deliberately includes a duplicate and a conflict.
"""),
analysis("""
ds = dataset()
summary=ds.summary();display(pd.DataFrame([summary]).drop(columns=['path','warnings'],errors='ignore'))
assert summary['duplicates_dropped']==1 and summary['quarantined_identities']==1
inventory={'Physiology':len(ds.physio),'Station':len(ds.station),'Events':len(ds.events)}
fig,axs=newfig(1,2,figsize=(12,4))
axs[0].bar(inventory.keys(),inventory.values());axs[0].set(title='Accepted records',ylabel='Records')
axs[1].bar(['Identical duplicates','Conflicting identities'],[summary['duplicates_dropped'],summary['quarantined_identities']],color=COLORS[1:3]);axs[1].set(title='Ingestion exceptions',ylabel='Count');save('03_ingestion')
"""),
md("""
## 5. Event time and arrival time

The agent only sees evidence available at the chosen cutoff. A late report does not retrospectively become available at its observation time. Delays below are from the synthetic input timestamps, not measured system latency. An official source class is a data label in this scenario, not authenticated real-world authority.
"""),
analysis("""
events=pd.DataFrame(dataset().events)
events['delay_s']=(pd.to_datetime(events.reported_at,utc=True,format='ISO8601')-pd.to_datetime(events.observed_at,utc=True,format='ISO8601')).dt.total_seconds()
fig,ax=newfig(figsize=(12,7));ax.barh(events.event_id,events.delay_s,color=COLORS[0]);ax.set(xlabel='Reported minus observed (s)',title='Synthetic event reporting delays');ax.invert_yaxis();save('04_event_delays')
fig,ax=newfig();events.source_class.value_counts().plot.barh(ax=ax,color=COLORS[2]);ax.set(xlabel='Event records',title='Evidence arrives from distinct source classes');save('05_source_classes')
"""),
md("""
## 6. Robust personal reference

The implementation computes z = (x − median) / max(1.4826 MAD, ε). Historical accepted samples must precede evaluation. “Calibrated” in this API means enough reference samples, not clinical calibration. This controlled reference shows resistance to one extreme value and the epsilon floor when variation is zero.
"""),
analysis("""
from umsf_agent.physio_rules import build_reference,robust_z
values=[69,70,71,70,72,69,71,70,70,71]
ref=build_reference(values,'test_feature','rest',1.0,8)
contaminated=build_reference(values+[200],'test_feature','rest',1.0,8)
flat=build_reference([70]*10,'test_feature','rest',1.0,8)
assert flat.scale==1 and robust_z(None,ref) is None
x=np.linspace(55,100,150)
fig,axs=newfig(1,2,figsize=(12,4.7))
axs[0].boxplot([values,values+[200]],tick_labels=['Original','One outlier']);axs[0].set(ylabel='Illustrative feature units',title='Reference sample perturbation')
axs[1].plot(x,[robust_z(v,ref) for v in x],label='Original reference');axs[1].plot(x,[robust_z(v,contaminated) for v in x],ls='--',label='Contaminated reference')
axs[1].set(xlabel='Evaluation value',ylabel='Robust z',title='Robust reference response');axs[1].legend();save('06_robust_reference')
"""),
md("""
## 7. Weighted score and missing channels

The declared feature weights sum to one. Each absolute z contribution is capped; a missing required channel makes the entire score undefined. It is not replaced by zero. The default cap and thresholds are development parameters.
"""),
analysis("""
from umsf_agent.physio_rules import weighted_score
z=np.linspace(-10,10,201)
score=np.array([[weighted_score({'a':a,'b':b},{'a':.5,'b':.5},6) for a in z] for b in z])
assert weighted_score({'a':None,'b':2},{'a':.5,'b':.5},6) is None
fig,ax=newfig();im=ax.imshow(score,origin='lower',extent=(-10,10,-10,10),aspect='auto',cmap='viridis');ax.set(xlabel='Feature A robust z',ylabel='Feature B robust z',title='Capped weighted deviation score');fig.colorbar(im,ax=ax,label='Score');save('07_score_surface')
"""),
md("""
## 8. Persistence is not a single-sample alarm

A flag uses the last L windows, requires the current window to be eligible and at least v_min eligible windows, then compares the fraction above τ to ρ. Ineligible windows are absent from the ratio. The example explicitly distinguishes unavailable from flag zero.
"""),
analysis("""
from umsf_agent.physio_rules import persistent_flag
scores=[1,4,4,None,4,2,4,None,4,4,4,2]
flag_rows=[]
for i in range(len(scores)):
    f=persistent_flag([(s is not None,s) for s in scores[:i+1]],5,3,.6,3)
    flag_rows.append({'window':i+1,'score':scores[i],'flag':f.value,'eligible_windows':f.eligible_windows,'reason':f.reason})
flags=pd.DataFrame(flag_rows);display(flags)
fig,axs=newfig(2,1,sharex=True,figsize=(11,6));axs[0].plot(flags.window,flags.score,'o-');axs[0].axhline(3,ls='--',color=COLORS[3]);axs[0].set(ylabel='Score',title='Persistence with missing windows')
axs[1].plot(flags.window,flags.flag,'o-',label='Flag (gaps = unavailable)');axs[1].set(xlabel='Window',ylabel='Flag',yticks=[0,1]);axs[1].legend();save('08_persistence')
"""),
md("""
## 9. Coverage-aware decision regions

For N roster members, at least max(n_min, ceil(C_min N)) need available flags. A group trigger also needs max(m_min, ceil(θ n)) positive flags. The heatmap enumerates all physically possible (n,m) combinations for N=12 using the original group gate. Grey cells have m>n and are impossible.
"""),
analysis("""
from umsf_agent.physio_rules import GroupParams,group_gate
params=GroupParams(6,.7,3,.3);roster=[f'W{i}' for i in range(12)]
gate_grid=np.full((13,13),np.nan)
for n in range(13):
    for m in range(n+1):
        g=group_gate('demo',roster,{w:(1 if i<m else 0) if i<n else None for i,w in enumerate(roster)},params)
        gate_grid[m,n]=2 if g.A else (1 if g.gate_available else 0)
cmap=ListedColormap(['#DDA35F','#92C1BF','#755DA2']);cmap.set_bad('#EEEEEE')
fig,ax=newfig();im=ax.imshow(gate_grid,origin='lower',cmap=cmap,vmin=-.5,vmax=2.5)
ax.set(xlabel='Eligible workers n',ylabel='Flagged workers m',title='N = 12: original group-gate decision regions',xticks=range(13),yticks=range(13))
cb=fig.colorbar(im,ax=ax,ticks=[0,1,2]);cb.ax.set_yticklabels(['Insufficient coverage','Adequate; no group trigger','Group trigger']);save('09_group_regions')
"""),
md("""
## 10. Roster size changes the effective threshold

A nominal 70% rule can be dominated by the minimum worker count. Some small rosters cannot satisfy a configuration at all. The separate demo policy uses n_min=3,m_min=2,θ=0.5; the paper illustration uses 6,3,0.3. We keep those parameter sets distinct.
"""),
analysis("""
from umsf_agent.physio_rules import GroupParams,threshold_feasibility
params=GroupParams(6,.7,3,.3)
rows=[]
for N in range(1,31):
    f=threshold_feasibility(N,params);rows.append({'N':N,'minimum_eligible':f.min_eligible,'coverage':f.effective_min_coverage_pct if f.feasible else np.nan})
feas=pd.DataFrame(rows)
fig,axs=newfig(1,2,figsize=(12,4.5));axs[0].step(feas.N,feas.minimum_eligible,where='mid');axs[0].plot(feas.N,feas.N,ls=':',color='gray');axs[0].set(xlabel='Roster N',ylabel='Required eligible n',title='Integer eligibility threshold')
axs[1].plot(feas.N,feas.coverage,'o-');axs[1].axhline(70,ls='--',color=COLORS[3]);axs[1].set(xlabel='Roster N',ylabel='Effective minimum coverage (%)',title='Count and percentage constraints interact');save('10_roster_thresholds')
"""),
md("""
## 11. Replay the agent chronologically

The replay covers 08:30–09:10 UTC in one-minute steps, using received/report timestamps at each cutoff. It invokes the original `Agent.step`, creates proposals and logs changes without approvals. Detailed snapshots are retained for inspection (stored as compact JSON). A fixed seed is already encoded in the supplied scenario; audit wall-clock timestamps vary by run.
"""),
analysis("""
R = replay(); tl = R.tl
print(f'{len(R.snapshots)} chronological assessments. Selected snapshot: {R.res["as_of"]}')
fig,axs=newfig(2,1,sharex=True,figsize=(12,6));axs[0].plot(tl.minute,tl.rescue_tasks,label='Tasks');axs[0].plot(tl.minute,tl.assigned,label='Assigned');axs[0].plot(tl.minute,tl.unassigned_urgent,label='Unassigned urgent');axs[0].set(ylabel='Count',title='Rescue proposals over the synthetic replay');axs[0].legend(ncol=3)
axs[1].plot(tl.minute,tl.observation_gaps,color=COLORS[3]);axs[1].set(xlabel='Minutes after 08:30 UTC',ylabel='Observation gaps');save('11_replay')
"""),
md("""
## 12. The roster remains visible during missingness

The personnel categories distinguish responder-confirmed accounting from device observations and unresolved whereabouts. A wearable observation is not a confirmed location. Counts cover the fixed roster; no category implies injury or casualty.
"""),
analysis("""
tl = replay().tl
people=pd.DataFrame(tl.personnel_counts.tolist()).fillna(0).astype(int)
assert people.sum(axis=1).eq(12).all()
fig,ax=newfig(figsize=(12,5));ax.stackplot(tl.minute,*[people[col] for col in people],labels=[human(x) for x in people],colors=COLORS)
ax.set(xlabel='Minutes after 08:30 UTC',ylabel='Roster members',title='Personnel accounting categories');ax.legend(loc='upper left',bbox_to_anchor=(1,1));save('12_personnel_accounting')
"""),
md("""
## 13. Coverage and group states over time

The synthetic zone Z2 shows why a high affected fraction does not stand alone. Eligibility depends on accepted reference windows, current data and persistence. Empty roster zones have undefined coverage and appear as gaps in the matrix.
"""),
analysis("""
R = replay(); tl, snapshots = R.tl, R.snapshots
zones=sorted(R.res['physiology']['zones'])
coverage=np.array([[r['physiology']['zones'][z]['decision']['group']['C_pct'] for r in snapshots] for z in zones],dtype=float)
fig,ax=newfig(figsize=(12,5));im=ax.imshow(coverage,aspect='auto',vmin=0,vmax=100,cmap='viridis',extent=(-.5,40.5,len(zones)-.5,-.5));ax.set(yticks=range(len(zones)),yticklabels=zones,xlabel='Minutes after 08:30 UTC',title='Available-flag coverage by zone');fig.colorbar(im,ax=ax,label='% of expected roster');save('13_coverage_timeline')
z2=pd.DataFrame([r['physiology']['zones']['Z2']['decision']['group'] for r in snapshots])
fig,ax=newfig();ax.plot(tl.minute,z2.C_pct,label='Coverage n/N');ax.plot(tl.minute,z2.p_pct,label='Flagged fraction m/n');ax.set(xlabel='Minutes after 08:30 UTC',ylabel='Percent',title='Z2: two denominators, two meanings');ax.legend();save('14_z2_fractions')
"""),
md("""
## 14. Zone state is typed evidence, not a damage score

M, H, P, F and U hold mechanical, hazard, personnel/presence, functional and uncertainty assertions. Current, stale, resolved and superseded records remain distinguishable. Counting evidence below describes software state only; more records do not mean more damage.
"""),
analysis("""
res = replay().res
layer_rows=[];assertion_rows=[]
for zid,z in res['incident']['zones'].items():
    for layer in ['M','H','P','F','U']:
        layer_rows.append({'zone':zid,'layer':layer,'count':len(z[layer])})
        assertion_rows.extend({'zone':zid,'layer':layer,**a} for a in z[layer])
ld=pd.DataFrame(layer_rows).pivot(index='zone',columns='layer',values='count')
fig,ax=newfig();ld.plot.bar(stacked=True,ax=ax,color=COLORS);ax.set(ylabel='Assertions',title='09:00 UTC: typed zone-state composition');save('15_evidence_layers')
assertions=pd.DataFrame(assertion_rows)
fig,ax=newfig();assertions.status.value_counts().plot.barh(ax=ax,color=COLORS[2]);ax.set(xlabel='Assertions',title='Historical evidence retains explicit status');save('16_evidence_status')
"""),
md("""
## 15. Source-qualified attribution and timing

A local impact composite remains unverified. A synthetic authoritative external report can support a statement that the source reported an event; it does not transform local sensor data into validated strike evidence. First display time depends on the replay cadence. Uncertain event times produce intervals rather than false precision.
"""),
analysis("""
res = replay().res
print(res['incident']['strike_statement_en'])
print('Rejected attribution records:',len(res['incident']['rejected_attributions']))
timing_rows=[]
for e in res['incident']['timing']:
    interval=e['T_report'].get('interval_s')
    if interval:timing_rows.append({'event':e['event_id'],'low':interval[0],'high':interval[1]})
tr=pd.DataFrame(timing_rows)
fig,ax=newfig(figsize=(10,5))
for i,r in tr.iterrows():ax.plot([r.low,r.high],[i,i],lw=5);ax.scatter([(r.low+r.high)/2],[i],color=COLORS[0])
ax.set(yticks=range(len(tr)),yticklabels=tr.event,xlabel='First-display delay interval (s)',title='Replay timing with source uncertainty — not measured network latency');save('17_timing_intervals')
"""),
md("""
## 16. Rescue eligibility before optimization

Each team–task pair must pass competence, availability, PPE, explicit access and a qualified time estimate. Unknown access blocks assignment and creates escalation; the task is retained. The matrix displays original eligibility outcomes, not a suggested entry route.
"""),
analysis("""
res = replay().res
pairs=res['rescue']['pairs'];teams=sorted({k.split('|')[0] for k in pairs});tasks=[x['task_id'] for x in res['rescue']['tasks']]
elig=np.zeros((len(teams),len(tasks)));cost=np.full_like(elig,np.nan)
for i,team in enumerate(teams):
    for j,task in enumerate(tasks):
        p=pairs.get(team+'|'+task,{})
        ok=p.get('e')==1 and p.get('a')==1 and p.get('delta_s') is not None
        elig[i,j]=ok
        if ok:cost[i,j]=p['delta_s']/60
fig,ax=newfig(figsize=(12,5));ax.imshow(elig,cmap='Greens',vmin=0,vmax=1,aspect='auto');ax.set(yticks=range(len(teams)),yticklabels=teams,xticks=range(len(tasks)),xticklabels=[human(t) for t in tasks],title='09:00 UTC: allowed team–task pairs');ax.tick_params(axis='x',rotation=25);save('18_eligibility')
fig,ax=newfig(figsize=(12,5));im=ax.imshow(cost,cmap='YlOrRd',aspect='auto');ax.set(yticks=range(len(teams)),yticklabels=teams,xticks=range(len(tasks)),xticklabels=[human(t) for t in tasks],title='Qualified travel-plus-setup estimates for allowed pairs');ax.tick_params(axis='x',rotation=25);fig.colorbar(im,ax=ax,label='Estimated minutes');save('19_assignment_cost')
"""),
md("""
## 17. Lexicographic priorities and the selected assignment

The objective first maximizes urgent tasks assigned, then policy priority, then minimizes total estimated time. It is not a survival model. The original exact Hungarian-based solver uses integer scaling. The unchanged test suite compares its objective with brute-force matching on small cases.
"""),
analysis("""
R = replay(); assign = R.assign
display(assign[['team_id','kind','zone_id','urgent','priority','delta_s']])
fig,ax=newfig();ax.barh(assign.team_id+' → '+assign.zone_id,assign.delta_s/60,color=[COLORS[3] if u else COLORS[0] for u in assign.urgent]);ax.set(xlabel='Estimated travel + setup (min)',title='Selected proposal: red marks policy-designated urgent tasks');save('20_selected_assignments')
from umsf_agent.assignment import AssignmentProblem,solve_lexicographic,brute_force
problem=AssignmentProblem(['T1','T2'],['urgent','routine'],{'urgent':1,'routine':0},{'urgent':1,'routine':1000},{('T1','urgent'):1000,('T1','routine'):1,('T2','routine'):2})
sol,triple=solve_lexicographic(problem);assert triple==brute_force(problem)[1]
print('Illustrative exact matching:',sol,'objective (urgent, priority, -seconds):',triple)
for item in R.res['rescue']['unassigned']:
    print(item['task_id'],':','; '.join(item['limiting_constraints']))
"""),
md("""
## 18. Service continuity reproduces a step frontier

The four-service analytical example has mandatory communications and emergency lighting. Capacity below three units is infeasible; it is never reported as zero-percent success. At six units the exact solution reaches 93.75% weighted service coverage. These illustrative units are separate from the kW/kWh resources of the larger scenario.
"""),
analysis("""
from umsf_agent.continuity import table16_solve
front = paper_checks().front; display(front)
fig,ax=newfig();ax.step(front.B,front.Q_pct,where='post',lw=2);ax.scatter(front.B,front.Q_pct);ax.axvspan(0,3,alpha=.15,color=COLORS[3],label='Infeasible below 3 units')
ax.set(xlabel='Justified capacity (illustrative units)',ylabel='Weighted service coverage Q (%)',title='Supplied analytical frontier: exact binary allocation');ax.legend();save('21_continuity_frontier')
solutions=[table16_solve(B) for B in range(13)]   # solve each capacity once (was once per service)
alloc=np.array([[s.y.get(name,0) if s.status=='OPTIMAL' else np.nan for s in solutions] for name in ['communications','emergency_lighting','water_support','production']])
fig,ax=newfig();ax.imshow(alloc,aspect='auto',cmap='Blues',vmin=0,vmax=1);ax.set(xticks=range(13),yticks=range(4),yticklabels=['Communications','Emergency lighting','Water support','Production'],xlabel='Capacity units',title='Optimal service selection (blank = infeasible)');save('22_service_selection')
"""),
md("""
## 19. Verified backup changes the feasible set

The two supplied scenarios differ in whether generator and fuel capacity are verified. We replay both through the same code; the no-backup replay runs in a background process started together with the tests (or now, if this cell runs first). INFEASIBLE remains a distinct result with no Q value. No mandatory life-safety service is relaxed to manufacture feasibility.
"""),
analysis("""
tl, other = replay().tl, replay_no_backup()
other_tl = other.tl
fig,axs=newfig(2,1,sharex=True,figsize=(12,6))
axs[0].step(tl.minute,tl.Q_pct,label='Verified backup scenario',where='post');axs[0].step(tl.minute,other_tl.Q_pct,label='No verified backup',where='post');axs[0].set(ylabel='Q (%)',title='Continuity response to evidence about capacity');axs[0].legend()
axs[1].step(tl.minute,tl.continuity_status.eq('INFEASIBLE'),label='Verified backup scenario',where='post');axs[1].step(tl.minute,other_tl.continuity_status.eq('INFEASIBLE'),label='No verified backup',where='post');axs[1].set(xlabel='Minutes after 08:30 UTC',ylabel='Infeasible (1=yes)');save('23_backup_comparison')
assert other.last_status=='INFEASIBLE'
"""),
md("""
## 20. Power, energy, staffing and communication are separate constraints

The larger scenario optimizes under several resources at once. Energy demand over a planning horizon cannot be replaced by a power rating. The chart normalizes each resource by its own justified capacity; heterogeneous units are not added.
"""),
analysis("""
R = replay(); cont, tl = R.cont, R.tl
resources=list(cont['resource_capacity'])
util=[100*cont['resource_use'].get(k,0)/cont['resource_capacity'][k] if cont['resource_capacity'][k]>0 else np.nan for k in resources]
fig,ax=newfig();ax.barh([human(k) for k in resources],util,color=COLORS[:len(resources)]);ax.axvline(100,ls='--',color=COLORS[3]);ax.set(xlabel='Use / justified capacity (%)',title='09:00 UTC: resource use in the exact continuity proposal');save('24_resource_use')
cap=pd.DataFrame([r['continuity']['result']['resource_capacity'] for r in R.snapshots])
fig,axs=newfig(2,1,sharex=True,figsize=(12,6))
for ax,key,label in zip(axs,['power_kw','energy_kwh'],['Power (kW)','Energy (kWh)']):ax.step(tl.minute,cap[key],where='post');ax.set_ylabel(label)
axs[0].set_title('Capacity bounds change when reports become available');axs[-1].set_xlabel('Minutes after 08:30 UTC');save('25_capacity_evidence')
"""),
md("""
## 21. Sensitivity to the justified power and energy bounds

This controlled sweep calls the same exact solver with the 09:00 service set, holding staffing and radio capacity fixed. It changes assumptions for study only; it does not certify an available power supply. Blank cells are infeasible. Unknown service admissibility remains excluded throughout.
"""),
analysis("""
from umsf_agent.continuity import Service,Resource,solve
R = replay(); cont = R.cont
services=[Service(**s) for s in R.res['continuity']['services']]
powers=np.arange(20,101,5);energies=np.arange(80,401,20);surface=np.full((len(energies),len(powers)),np.nan)
for i,energy in enumerate(energies):
    for j,power in enumerate(powers):
        rr={k:Resource(k,k,v) for k,v in cont['resource_capacity'].items()};rr['power_kw'].lower_bound=int(power);rr['energy_kwh'].lower_bound=int(energy)
        result=solve(services,rr);surface[i,j]=result.Q_pct if result.Q_pct is not None else np.nan
fig,ax=newfig();im=ax.imshow(surface,origin='lower',aspect='auto',extent=(17.5,102.5,70,410),vmin=0,vmax=100,cmap='viridis');ax.set(xlabel='Power lower bound (kW)',ylabel='Energy lower bound (kWh)',title='Exact continuity sensitivity; other constraints held fixed');fig.colorbar(im,ax=ax,label='Q (%)');save('26_capacity_surface')
"""),
md("""
## 22. Recovery schedule: a candidate, not an optimum

The recovery module uses hard prerequisites, critical-path analysis and a serial schedule-generation heuristic with crew/equipment constraints. Its candidate schedule is not globally optimized. All durations are planning assumptions. Blocked tasks remain visible, and industrial actuation is excluded.
"""),
analysis("""
R = replay(); recovery, scheduled = R.recovery, R.scheduled
fig,ax=newfig(figsize=(12,6))
for i,(_,r) in enumerate(scheduled.iterrows()):
    ax.barh(i,r.finish_offset_min-r.start_offset_min,left=r.start_offset_min,color=COLORS[3] if r.critical else COLORS[0]);ax.text(r.start_offset_min+1,i,str(r.crew),va='center',color='white',fontsize=9)
ax.set(yticks=range(len(scheduled)),yticklabels=[human(k)+' / '+z for k,z in zip(scheduled.kind,scheduled.zone_id)],xlabel='Minutes after 09:00 UTC',title='Recovery candidate schedule (red = CPM-critical tasks)');ax.invert_yaxis();save('27_recovery_gantt')
display(recovery[['kind','zone_id','status','crew','blocked_reasons']])
"""),
md("""
## 23. Prerequisites and schedule validation

This matrix reads prerequisites from the generated tasks. A scheduled task cannot start before any scheduled predecessor finishes. Crews cannot overlap in this single-capacity model. Passing these checks verifies the candidate’s internal feasibility, not field access or actual completion.
"""),
analysis("""
R = replay(); recovery, scheduled, res = R.recovery, R.scheduled, R.res
ids=list(recovery.task_id);dep=np.zeros((len(ids),len(ids)))
by_id={t['task_id']:t for t in res['recovery']['tasks']}
for i,task in enumerate(ids):
    for pred in by_id[task]['prerequisites']:
        if pred in ids:dep[i,ids.index(pred)]=1
for t in res['recovery']['tasks']:
    if t['status']=='scheduled_candidate':
        for p in t['prerequisites']:
            assert by_id[p]['status']=='scheduled_candidate'
            assert t['start_offset_min']>=by_id[p]['finish_offset_min']
for crew,g in scheduled.groupby('crew'):
    g=g.sort_values('start_offset_min');assert all(a<=b for a,b in zip(g.finish_offset_min.iloc[:-1],g.start_offset_min.iloc[1:]))
fig,ax=newfig(figsize=(11,7));ax.imshow(dep,cmap='Purples',vmin=0,vmax=1);labels=[str(i+1)+': '+human(by_id[k]['kind'])+' / '+str(by_id[k]['zone_id']) for i,k in enumerate(ids)]
ax.set(yticks=range(len(ids)),yticklabels=labels,xticks=range(len(ids)),xticklabels=range(1,len(ids)+1),xlabel='Prerequisite task number',title='Recovery dependency matrix');save('28_dependencies')
"""),
md("""
## 24. Proposal authority is explicit

There are seven decision domains with named authorizing roles. The notebook leaves all operational proposals awaiting authorization. Role checking in this prototype validates supplied role labels; it is not an identity-provider integration. A demonstration below writes simulated decisions only to a separate demonstration audit.
"""),
analysis("""
packages = replay().packages
authority=pd.DataFrame([{'domain':p['domain'],'roles':', '.join(p['authorising_roles']),'status':p['status']} for p in packages]);display(authority)
assert all(p['proposal'] and p['status']=='awaiting_authorisation' for p in packages)
roles=sorted({r for p in packages for r in p['authorising_roles']});mat=np.array([[r in p['authorising_roles'] for r in roles] for p in packages])
fig,ax=newfig(figsize=(12,6));ax.imshow(mat,aspect='auto',cmap='Blues');ax.set(yticks=range(len(packages)),yticklabels=[human(p['domain']) for p in packages],xticks=range(len(roles)),xticklabels=[human(r) for r in roles],title='Proposal domains and accepted role labels');ax.tick_params(axis='x',rotation=40);save('29_authority')
"""),
md("""
## 25. Audit integrity and its limits

The original SHA-256 chain detects edits to stored entries. It is not a digital signature, authenticated identity system or tamper-proof storage. Rewriting the full chain or truncating its tail needs an external trusted checkpoint to detect reliably. We tamper only with a disposable copy, preserving the original replay audit. The demonstration audit is recreated on every run.
"""),
analysis("""
from umsf_agent.audit import AuditLog,verify_chain
from umsf_agent.agent import record_authorisation
R = replay(); agent, packages = R.agent, R.packages
assert verify_chain(agent.audit.path)[0]
audit_rows=list(agent.audit.entries());savejson('audit_summary.json',{'entries':len(audit_rows),'chain_valid':True})
copy_path=OUT/'tampered_demo.jsonl';copy_rows=[dict(e) for e in audit_rows];copy_rows[1]={**copy_rows[1],'payload':{'deliberately_modified':True}}
copy_path.write_text('\\n'.join(json.dumps(e) for e in copy_rows)+'\\n');assert not verify_chain(str(copy_path))[0]
(OUT/'simulated_authority_demo.jsonl').unlink(missing_ok=True)   # fresh demonstration chain
demo_audit=AuditLog(str(OUT/'simulated_authority_demo.jsonl'))
try:record_authorisation(demo_audit,packages[0],'approved','unrecognised_role','DEMO','Role check demonstration')
except ValueError: print('Wrong role correctly rejected.')
else: raise AssertionError('Role check failed')
record_authorisation(demo_audit,packages[0],'approved',packages[0]['authorising_roles'][0],'SIMULATION-ONLY','Educational simulation; no real authorization',simulated=True)
assert verify_chain(demo_audit.path)[0]
fig,ax=newfig();pd.Series([e['entry_type'] for e in audit_rows]).value_counts().plot.barh(ax=ax,color=COLORS[0]);ax.set(xlabel='Audit entries',title='Replay audit trail by entry type');save('30_audit_events')
"""),
md("""
## 26. Optional language model: a deliberately limited boundary

No external LLM is needed or called. The original post-check is a lexical/numeric heuristic, not a semantic truth verifier. It rejects some forbidden phrases and unsupported numbers, but its source-text exception and tolerance of small list numbers create known limits. The experiment exposes these limits rather than describing the filter as a safety guarantee. All computations remain outside the LLM.
"""),
analysis("""
from umsf_agent.llm import post_check
texts=[('Supported count','There are 12 workers.','12 workers'),('Unsupported count','There are 999 workers.','12 workers'),('Forbidden phrase','The site is safe to enter.','12 workers'),('Source phrase exception','The site is safe to enter.','Warning: never claim safe to enter.'),('Small number tolerance','There are 7 available teams.','12 workers')]
filter_rows=[{'case':name,'accepted':post_check(text,corpus,['safe to enter'])['ok']} for name,text,corpus in texts]
display(pd.DataFrame(filter_rows))
assert [r['accepted'] for r in filter_rows]==[True,False,False,True,True]
savejson('llm_filter_demonstration.json',filter_rows)
print('Live LLM API compatibility is not tested. The notebook is fully offline apart from optional dependency installation.')
"""),
md("""
## 27. English explorer and report

The explorer contains an offline snapshot selector and English summaries of the actual replay outputs. It embeds its data and uses no external JavaScript, map tiles or APIs. It is a presentation companion, not a control interface. Raw package outputs remain available separately for audit.
"""),
analysis(f'''
R = replay(); res, cont = R.res, R.cont
explorer_data=[{{'time':r['as_of'],'continuity':r['continuity']['result']['status'],'q':r['continuity']['result']['Q_pct'],
    'tasks':len(r['rescue']['tasks']),'assigned':len(r['rescue']['assignments']),'unassigned_urgent':len(r['rescue']['unassigned_urgent']),
    'zones':[{{'zone':z,'coverage':v['decision']['group']['C_pct'],'state':v['decision']['label_en']}} for z,v in r['physiology']['zones'].items()]}}
    for r in R.snapshots]
EXPLORER_TEMPLATE = {EXPLORER!r}
page=EXPLORER_TEMPLATE.replace('__DATA__',json.dumps(explorer_data).replace('<','\\\\u003c'))
(OUT/'interactive_explorer.html').write_text(page)
report=(f"# UMSF Agent Laboratory — English summary\\n\\nSynthetic scenario. No operational authorization or actuation.\\n\\n"
        f"Selected time: {{res['as_of']}}\\n\\nContinuity status: {{cont['status']}}; weighted coverage: {{cont['Q_pct']:.2f}}%.\\n\\n"
        f"Rescue tasks: {{len(res['rescue']['tasks'])}}; proposed assignments: {{len(R.assign)}}; unresolved urgent: {{len(res['rescue']['unassigned_urgent'])}}.\\n\\n"
        f"Recovery: {{len(R.scheduled)}} scheduled candidates; {{len(res['recovery']['blocked'])}} blocked tasks.\\n\\n{{res['incident']['strike_statement_en']}}\\n")
(OUT/'REPORT_EN.md').write_text(report)
display(HTML('<p><b>Offline explorer created.</b> Open interactive_explorer.html from the results ZIP in a browser.</p>'))
'''),
md("""
## 28. Verification ledger and export

Every result is regenerated from the embedded source. Assertions verify source integrity, the original test suite, analytical targets, roster accounting, schedule precedence, role rejection and audit-tamper detection. Execution evidence describes the tested local environment; the hosted Colab frontend and live LLM service are not claimed as tested. This cell is self-sufficient: it computes any missing test, check or replay itself and reports figure sections not yet executed. The archive is written to `umsf_agent_runs/latest/UMSF_AI_Agent_Lab_results.zip`.
"""),
analysis("""
verification_ledger = verification()
print(json.dumps(verification_ledger, indent=2))
if verification_ledger['figures'] < EXPECTED_FIGURES:
    print(f"Note: {EXPECTED_FIGURES-verification_ledger['figures']} figure(s) not produced yet - run the remaining sections, then this cell again.")
latest=RUNS/'latest'; latest.mkdir(exist_ok=True)
archive=latest/'UMSF_AI_Agent_Lab_results.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(OUT.rglob('*')):
        if p.is_file() and not p.name.startswith('.'):z.write(p,p.relative_to(RUN).as_posix())
print(f'Results archive: {os.path.relpath(archive)} ({archive.stat().st_size:,} bytes)')
# Optional Colab browser download:
# from google.colab import files
# files.download(str(archive))
"""),
md("""
## Reuse, interpretation and next experiments

The unchanged source lives in `umsf-incident-ai-agent/`; the additional P1 integration fixture is in `umsf-incident-dataset/`. Both carry their original licensing and citation metadata. Source SHA-256 values are embedded and verified. Original Ukrainian labels are retained in archived source and raw audit data; all new notebook explanations and plotted labels are English. The notebook runtime is `notebook/umsf_ai_lab.py` in the release.

For a controlled experiment, modify one policy value or one synthetic input at a time (in `umsf_agent_runs/project/`), preserve the variant identity, run Section 0 again to clear cached results and rerun. Note that the start cell re-extracts the project if a verified source file was changed, so keep variants in a separate copy. Compare eligibility and feasibility before interpreting objective values. Distinguish the exact rescue/continuity solvers from heuristic recovery scheduling. Do not interpret a hypothetical access override as real authorization.

The source has an optional external language-model adapter. Its model identifiers and API compatibility are outside this offline validation. The notebook never invokes that adapter. The lexical post-check is illustrative defense in depth and has the documented limitations demonstrated above.

**Publication files:** the full release includes a clean notebook, executed notebook, HTML report, offline explorer, PNG/SVG figures, CSV/JSON outputs, original tests, source archive, checksum inventory, MIT license, `CITATION.cff`, `.zenodo.json` and a ready-to-copy English description. A Zenodo DOI must be assigned by the repository; none is fabricated here.
"""),
    ]


def main():
    sha, text, size = build_payload()
    nb = new_notebook(cells=cells(sha, text, size))
    nb.metadata = {'colab': {'name': 'UMSF_AI_Agent_Lab.ipynb', 'provenance': [], 'toc_visible': True},
                   'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
                   'language_info': {'name': 'python', 'version': '3.12'}}
    for i, cell in enumerate(nb.cells):
        cell['id'] = f'umsf-ai-{i:02d}'
    nbformat.validate(nb)
    nbformat.write(nb, ROOT / 'UMSF_AI_Agent_Lab.ipynb')
    print(json.dumps({'cells': len(nb.cells), 'code_cells': sum(c.cell_type == 'code' for c in nb.cells),
                      'payload_bytes': size, 'payload_sha256': sha,
                      'notebook_bytes': (ROOT / 'UMSF_AI_Agent_Lab.ipynb').stat().st_size}, indent=2))


if __name__ == '__main__':
    main()
