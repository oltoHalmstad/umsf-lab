"""UMSF Incident Lab runtime (notebook release 1.2.0).

Written to disk by the notebook's setup section and imported by every analysis cell with
``from umsf_lab import *``. Importing it is idempotent and cheap after the first time:

* installs only missing analysis libraries;
* verifies the embedded payload (``umsf_payload.py``) and the original source/data hashes, and
  extracts the project once into ``umsf_notebook_runs/project`` (reused while it verifies);
* defines shared plotting conventions and output helpers;
* exposes lazily computed, cached analysis states (incident data, Study A/B, replay, checks).

Because every shared state is computed on first use, any analysis cell can run on its own, in any
order, and after a kernel restart. The analytical core ``umsf_dataset`` (v1.0.0) is unchanged.
"""
from __future__ import annotations

import base64, copy, functools, hashlib, html, importlib.metadata, importlib.util, io, json, os
import platform, shutil, sqlite3, subprocess, sys, time, zipfile
from pathlib import Path
from types import SimpleNamespace

NOTEBOOK_RELEASE = '1.2.0'
ANALYTICAL_CORE = '1.0.0'
assert sys.version_info >= (3, 10), 'Python 3.10 or later is required.'

# ---------------------------------------------------------------- 1. dependencies
REQUIREMENTS = {'numpy': 'numpy>=1.24,<3', 'pandas': 'pandas>=2,<4', 'matplotlib': 'matplotlib>=3.7,<4',
                'seaborn': 'seaborn>=0.12,<1', 'cryptography': 'cryptography>=41'}
MISSING_INSTALLED = [req for mod, req in REQUIREMENTS.items() if importlib.util.find_spec(mod) is None]
if MISSING_INSTALLED:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', *MISSING_INSTALLED])
    importlib.invalidate_caches()

# ---------------------------------------------------------------- 2. verified project
RUNS = Path.cwd() / 'umsf_notebook_runs'
PROJECT = RUNS / 'project'
_MARKER = PROJECT / '.payload_sha256'


def _verify_inventory(root: Path) -> dict:
    inventory = json.loads((root / 'provenance/source_inventory.json').read_text())
    for name, digest in inventory['retained_files'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise AssertionError(f'Original file changed: {name}')
    return inventory


def _prepare_project():
    from umsf_payload import PAYLOAD, PAYLOAD_SHA256
    if _MARKER.exists() and _MARKER.read_text().strip() == PAYLOAD_SHA256:
        try:
            return PAYLOAD_SHA256, _verify_inventory(PROJECT), 'reused'
        except (AssertionError, OSError):
            pass  # damaged or edited copy: extract again below
    blob = base64.b85decode(''.join(PAYLOAD.split()))
    assert hashlib.sha256(blob).hexdigest() == PAYLOAD_SHA256, 'Embedded payload checksum mismatch.'
    staging = RUNS / '.staging'
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for item in archive.infolist():
            assert (staging / item.filename).resolve().is_relative_to(staging.resolve()), 'Unsafe archive path.'
        archive.extractall(staging)
    inventory = _verify_inventory(staging)
    shutil.rmtree(PROJECT, ignore_errors=True)
    staging.rename(PROJECT)
    _MARKER.write_text(PAYLOAD_SHA256)
    return PAYLOAD_SHA256, inventory, 'extracted'


PAYLOAD_SHA256, SOURCE_INVENTORY, PROJECT_STATUS = _prepare_project()
if str(PROJECT / 'src') not in sys.path:
    sys.path.insert(0, str(PROJECT / 'src'))
if str(PROJECT / 'src') not in os.environ.get('PYTHONPATH', '').split(os.pathsep):
    os.environ['PYTHONPATH'] = os.pathsep.join(filter(None, [str(PROJECT / 'src'), os.environ.get('PYTHONPATH')]))
DATA, OUT = PROJECT / 'data', PROJECT / 'results'
FIG = OUT / 'figures'
FIG.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 3. libraries and conventions
import numpy as np, pandas as pd, matplotlib, seaborn as sns
try:
    _ip = get_ipython()  # noqa: F821 - defined inside IPython/Colab
except NameError:
    try:
        from IPython import get_ipython as _get_ipython
        _ip = _get_ipython()
    except ImportError:
        _ip = None
if _ip is not None and 'inline' not in matplotlib.get_backend().lower():
    _ip.run_line_magic('matplotlib', 'inline')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import FancyBboxPatch
from IPython.display import display, HTML, Markdown, FileLink

from umsf_dataset.synth import study_a, study_b, incident, bench
from umsf_dataset import frames, reproduce, summaries
from umsf_dataset.validate import validate_record
from umsf_dataset.export import sizing
from umsf_dataset.timeutil import from_epoch, to_epoch

sns.set_theme(style='whitegrid', context='notebook', palette='colorblind')
plt.rcParams.update({'figure.dpi': 110, 'savefig.dpi': 180, 'font.size': 10,
                     'figure.constrained_layout.use': True, 'axes.spines.top': False,
                     'axes.spines.right': False, 'svg.fonttype': 'none', 'svg.hashsalt': 'umsf'})
COL = {'blue': '#2463A4', 'teal': '#168A86', 'amber': '#DD922D', 'red': '#BD4C53',
       'grey': '#A5AEB9', 'ink': '#203044', 'purple': '#8060A8'}
STATION_FIELDS = [('vib_peak_g', 'Vibration peak (g)'), ('tilt_deg', 'Inclination (deg)'),
                  ('pressure_delta_pa', 'Pressure excursion (Pa)'), ('gas_v', 'Uncalibrated gas channel (V)'),
                  ('sound_index', 'Sound index (a.u.)'), ('temp_c', 'Temperature (°C)')]
EXPECTED_FIGURES = 30


def read_json(path):
    return json.loads(Path(path).read_text())


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def save_table(name, frame):
    """Write a CSV result table and return the frame for display."""
    frame.to_csv(OUT / f'{name}.csv', index=False)
    return frame


def figure_catalog() -> dict:
    path = OUT / 'figure_catalog.json'
    return read_json(path) if path.exists() else {}


def savefig(name, caption, fig=None):
    """Save the current figure as PNG + SVG, register it in the persistent catalog and show it."""
    fig = fig or plt.gcf()
    fig.savefig(FIG / f'{name}.png', bbox_inches='tight')
    fig.savefig(FIG / f'{name}.svg', bbox_inches='tight', metadata={'Date': None})
    catalog = figure_catalog()
    catalog[name] = caption
    (OUT / 'figure_catalog.json').write_text(json.dumps(dict(sorted(catalog.items())), indent=2))
    plt.show()
    plt.close(fig)
    display(Markdown('**Interpretation.** ' + caption))


def _timed(label):
    """Cache a zero-argument state builder and report its first computation."""
    def wrap(fn):
        cached = functools.cache(fn)

        @functools.wraps(fn)
        def inner():
            first = cached.cache_info().currsize == 0
            started = time.perf_counter()
            value = cached()
            if first:
                print(f'[umsf_lab] {label} prepared in {time.perf_counter() - started:.1f} s')
            return value
        inner.cache_clear = cached.cache_clear
        return inner
    return wrap


@functools.cache
def environment() -> dict:
    env = {'python': platform.python_version(), 'platform': platform.system(), 'sqlite': sqlite3.sqlite_version,
           'packages': {p: importlib.metadata.version(p) for p in REQUIREMENTS},
           'notebook_release': NOTEBOOK_RELEASE, 'analytical_core': ANALYTICAL_CORE,
           'payload_sha256': PAYLOAD_SHA256}
    (OUT / 'environment.json').write_text(json.dumps(env, indent=2))
    return env


# ---------------------------------------------------------------- 4. lazily computed states
@_timed('Incident scenario')
def incident_data() -> SimpleNamespace:
    """Incident records (raw dicts and DataFrames), rosters, manifest and time origin."""
    physio_records = read_jsonl(DATA / 'incident/physio.jsonl')
    station_records = read_jsonl(DATA / 'incident/station.jsonl')
    event_records = read_jsonl(DATA / 'incident/events.jsonl')
    manifest = read_json(DATA / 'incident/manifest.json')
    t0 = pd.Timestamp(manifest['t0'])
    physio, station, events = map(pd.DataFrame, [physio_records, station_records, event_records])
    for df in (physio, station):
        df['time'] = pd.to_datetime(df['measured_at'], utc=True, format='ISO8601')
        df['received_time'] = pd.to_datetime(df['received_at'], utc=True, format='ISO8601')
        df['minute'] = (df['time'] - t0).dt.total_seconds() / 60
        df['delay_s'] = (df['received_time'] - df['time']).dt.total_seconds()
    events['time'] = pd.to_datetime(events['observed_at'], utc=True, format='ISO8601')
    events['minute'] = (events['time'] - t0).dt.total_seconds() / 60
    rosters = {r['site_id']: r for r in read_json(DATA / 'incident/roster.json')['sites']}
    return SimpleNamespace(physio_records=physio_records, station_records=station_records,
                           event_records=event_records, physio=physio, station=station, events=events,
                           rosters=rosters, manifest=manifest, t0=t0, t0_epoch=to_epoch(manifest['t0']))


@_timed('Study A reference simulation')
def study_a_reference() -> SimpleNamespace:
    """Reference Study A run (seed 20260908): records, episodes, decisions with truth labels, metrics."""
    records, episodes, degraded = study_a.generate()
    decisions = study_a.detect(records)
    metrics = study_a.evaluate(records, episodes, degraded, decisions)
    assert [metrics[k] for k in ['TP', 'FP', 'FN', 'TN']] == [280, 0, 120, 4400]
    a, d = pd.DataFrame(records), pd.DataFrame(decisions)
    assert len(a) == 40320 and len(d) == 4800
    truth = {(e['day'] + 1, f"Z{e['zone'] + 1}", t): e['strength']
             for e in episodes for t in range(e['start'], e['start'] + e['minutes'])}
    d['truth'] = [truth.get(key, 'background') for key in zip(d.day, d.zone, d.minute)]
    d['row'] = 'Day ' + d.day.astype(str) + ' / ' + d.zone
    (OUT / 'study_a_metrics.json').write_text(json.dumps(metrics, indent=2))
    return SimpleNamespace(records=records, episodes=episodes, degraded=degraded, decisions=decisions,
                           a=a, d=d, metrics=metrics,
                           target_keys=frozenset(k for k, v in zip(zip(d.day, d.zone, d.minute), d.truth)
                                                 if v != 'background'))


@_timed('Study B ingestion run')
def study_b_reference() -> SimpleNamespace:
    """Study B pipeline output (store, exports, summaries) and the generated base stream."""
    result = study_b.run(str(OUT / 'study_b'))
    assert [result[k] for k in ['input_lines', 'unique_identities', 'duplicates', 'conflicts', 'rejected',
                                'exported', 'summaries']] == [2173, 2160, 6, 1, 6, 2159, 12]
    return SimpleNamespace(result=result, generated=study_b.generate(),
                           summaries=pd.DataFrame(read_json(OUT / 'study_b/exports/summaries_5min.json')),
                           export=pd.DataFrame(read_jsonl(OUT / 'study_b/exports/physio_2026-09-08.jsonl')))


def _latest_candidates(indexed, t):
    """Per device, the first record with the greatest measurement time among those measured and
    received by ``t`` - exactly the record the core state functions select. Passing only these
    candidates leaves their result unchanged while avoiding re-parsing every timestamp."""
    best = {}
    for m, rc, record in indexed:
        if rc <= t and m <= t:
            device = record['device_id']
            if device not in best or m > best[device][0]:
                best[device] = (m, record)
    return [record for _, record in best.values()]


@_timed('Incident as-of replay')
def incident_replay() -> SimpleNamespace:
    """Original as-of state functions evaluated every 30 s; future arrivals cannot leak backwards."""
    inc = incident_data()
    index = lambda rows: [(to_epoch(r['measured_at']), to_epoch(r['received_at']), r) for r in rows]
    by_site = {site: (index([r for r in inc.physio_records if r['site_id'] == site]),
                      index([r for r in inc.station_records if r['site_id'] == site]))
               for site in inc.rosters}
    personnel_rows, station_rows = [], []
    for seconds in range(0, 1801, 30):
        t = inc.t0_epoch + seconds
        at = from_epoch(t)
        for site, roster in inc.rosters.items():
            physio_idx, station_idx = by_site[site]
            current = summaries.physio_current_state(_latest_candidates(physio_idx, t), roster, at)
            for device, item in current['devices'].items():
                personnel_rows.append({'minute': seconds / 60, 'site': site, 'device': device, **item})
            zone_state = summaries.station_zone_state(_latest_candidates(station_idx, t), inc.event_records,
                                                      roster, at)
            for zone, z in zone_state['zones'].items():
                for device, item in z['nodes'].items():
                    station_rows.append({'minute': seconds / 60, 'site': site, 'zone': zone, 'device': device,
                                         'status': item['status'], 'age_s': item['age_s']})
    # Equivalence guard: the candidate pre-selection must reproduce the unfiltered core result.
    for seconds in (450, 1800):
        at = from_epoch(inc.t0_epoch + seconds)
        for site, roster in inc.rosters.items():
            full = summaries.physio_current_state(inc.physio_records, roster, at)['devices']
            assert full == {r['device']: {k: v for k, v in r.items() if k not in ('minute', 'site', 'device')}
                            for r in personnel_rows if r['minute'] == seconds / 60 and r['site'] == site}
            full = summaries.station_zone_state(inc.station_records, inc.event_records, roster, at)['zones']
            got = {(r['zone'], r['device']): r['status'] for r in station_rows
                   if r['minute'] == seconds / 60 and r['site'] == site}
            assert got == {(z, n): v['status'] for z, zz in full.items() for n, v in zz['nodes'].items()}
    personnel, station = pd.DataFrame(personnel_rows), pd.DataFrame(station_rows)
    save_table('personnel_asof_replay', personnel)
    save_table('station_asof_replay', station)
    return SimpleNamespace(personnel=personnel, station=station)


@_timed('Semantic regression checks')
def semantic_checks() -> list:
    inc = incident_data()
    checks = []
    bad = copy.deepcopy(inc.physio_records[0]); bad['data_origin'] = 'measured'
    checks.append({'Check': 'Measured origin rejected by default', 'Passed': bool(validate_record(bad)[1])})
    bad = copy.deepcopy(inc.physio_records[0]); bad['hr_bpm'] = 412
    checks.append({'Check': 'Out-of-range HR rejected', 'Passed': bool(validate_record(bad)[1])})
    bad = copy.deepcopy(next(e for e in inc.event_records if e['event_type'] == 'external_strike_report'))
    bad['source_class'] = 'stationary_node'
    checks.append({'Check': 'Local source cannot assert external strike report',
                   'Passed': bool(validate_record(bad)[1])})
    checks.append({'Check': 'Incident SpO2 remains null',
                   'Passed': all(r['spo2_pct'] is None for r in inc.physio_records)})
    loss_at = from_epoch(inc.t0_epoch + incident.T_SA1_LOSS + 5)
    loss = summaries.station_zone_state(inc.station_records, inc.event_records, inc.rosters['SITE-A'], loss_at)
    checks.append({'Check': 'Link loss produces unknown station evidence',
                   'Passed': loss['zones']['A-Z1']['nodes']['SA1']['status'] == 'unknown'})
    assert all(c['Passed'] for c in checks), checks
    save_table('semantic_checks', pd.DataFrame(checks))
    return checks


@_timed('Protocol checks')
def protocol_checks() -> SimpleNamespace:
    lines = (DATA / 'bench/stage2_station_frames.hex').read_text().splitlines()
    raw = [bytes.fromhex(line.split()[-1]) for line in lines if line.strip()]
    decoded = [frames.decode_frame(x) for x in raw]
    assert all(x['crc_ok'] for x in decoded)
    parts = frames.fragment(raw[0], att_payload=20, msg_id=7)
    reassembler, rebuilt = frames.Reassembler(), None
    for part in reversed(parts):
        rebuilt = reassembler.feed(part, source='synthetic-station', now=0.0) or rebuilt
    assert rebuilt == raw[0]
    compact = frames.encode_compact(1, 7, {'vib_peak_cg': 3, 'tilt_ddeg': 4, 'pressure_dhpa': 10037, 'temp': 2190,
                                           'gas_mv': 800, 'sound_index': 262, 'flags': 1, 'battery_pct': 90})
    corrupt = bytearray(compact); corrupt[5] ^= 1
    assert frames.decode_compact(compact)['crc_ok'] and not frames.decode_compact(bytes(corrupt))['crc_ok']
    checks = {'decoded_frames': len(decoded), 'all_crc_valid': True, 'reassembly_exact': True,
              'compact_bytes': len(compact), 'corruption_detected': True}
    (OUT / 'protocol_checks.json').write_text(json.dumps(checks, indent=2))
    return SimpleNamespace(checks=checks, raw_frames=raw, parts=parts, compact=compact)


@_timed('Cryptographic demonstration')
def crypto_demo() -> dict:
    from umsf_dataset.synth.protection import run_protection_demo
    result = run_protection_demo(study_a_reference().records, study_a.SEED)
    assert result['available'] and result['ordinary_verified'] == 40320
    assert all(v['rejected'] == v['cases'] == 1000 for v in result['negative'].values())
    (OUT / 'crypto_results.json').write_text(json.dumps(result, indent=2))
    return result


@_timed('Original test suite and reference comparison')
def verification() -> SimpleNamespace:
    """Original unit tests (subprocess) overlap with the in-process reference reproduction and checks."""
    started = time.perf_counter()
    tests = subprocess.Popen([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=PROJECT,
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=dict(os.environ))
    try:
        comparison = reproduce.run(str(OUT / 'reference_reproduction'), protection=True)
        checks = {'semantic_checks': semantic_checks(), 'protocol_checks': protocol_checks().checks,
                  'crypto_verified': crypto_demo()['ordinary_verified'], 'incident_records_valid': incident_valid()}
        test_output, _ = tests.communicate(timeout=600)
    finally:
        if tests.poll() is None:
            tests.kill()
    (OUT / 'original_tests.txt').write_text(test_output)
    assert tests.returncode == 0, 'Original test suite failed; inspect results/original_tests.txt.\n' + test_output
    table = pd.DataFrame(comparison['rows'])
    assert comparison['ok'] and table.status.eq('OK').all(), table[table.status != 'OK']
    save_table('reference_comparison', table)
    (OUT / 'reference_comparison.txt').write_text(reproduce.format_table(comparison['rows']))
    summary = {'original_test_returncode': tests.returncode,
               'original_tests_line': next((l for l in test_output.splitlines() if l.startswith('Ran ')), ''),
               'reference_rows': len(table), 'reference_all_ok': bool(table.status.eq('OK').all()),
               **checks,
               'source_files_verified': len(SOURCE_INVENTORY['retained_files']),
               'verification_elapsed_s': round(time.perf_counter() - started, 3)}
    (OUT / 'verification.json').write_text(json.dumps(summary, indent=2))
    return SimpleNamespace(summary=summary, table=table, test_output=test_output)


@functools.cache
def incident_valid() -> bool:
    inc = incident_data()
    invalid = [(kind, i, errors) for kind, rows in [('physio', inc.physio_records), ('station', inc.station_records),
                                                    ('event', inc.event_records)]
               for i, row in enumerate(rows) for errors in [validate_record(row)[1]] if errors]
    assert not invalid, invalid[:3]
    return True


# ---------------------------------------------------------------- 5. dashboard and export
def dashboard_html() -> str:
    """Offline explorer: columnar data (compact) inserted into the dependency-free HTML template."""
    inc, replay = incident_data(), incident_replay()
    t0 = inc.t0_epoch
    nodes = sorted(inc.station.device_id.unique())
    node_index = {n: i for i, n in enumerate(nodes)}
    columns = {'node': [node_index[r['device_id']] for r in inc.station_records],
               's': [round(to_epoch(r['measured_at']) - t0, 3) for r in inc.station_records],
               'arrival': [round(to_epoch(r['received_at']) - t0, 3) for r in inc.station_records]}
    for field, _ in STATION_FIELDS:
        columns[field] = [r.get(field) for r in inc.station_records]
    data = {'t0': str(inc.t0), 'nodes': nodes, 'fields': dict(STATION_FIELDS),
            'snapshots': [g.set_index('device').status.to_dict()
                          for _, g in replay.station.groupby('minute', sort=True)],
            'columns': columns,
            'events': [{'reported': to_epoch(e['reported_at']) - t0, 'type': e['event_type'],
                        'source': e['source_class'], 'site': e['site_id']} for e in inc.event_records]}
    template = (PROJECT / 'docs/dashboard_template.html').read_text()
    page = template.replace('__DATA__', json.dumps(data, separators=(',', ':')))
    (OUT / 'interactive_dashboard.html').write_text(page)
    return page


def status() -> None:
    """Print a one-screen summary of the runtime and the outputs produced so far."""
    env = environment()
    figures = sorted(p.stem for p in FIG.glob('*.png'))
    print(f'UMSF Incident Lab {NOTEBOOK_RELEASE} | core {ANALYTICAL_CORE} | Python {env["python"]}')
    print(f'Payload {PAYLOAD_SHA256[:16]}… {PROJECT_STATUS}; original files verified: '
          f'{len(SOURCE_INVENTORY["retained_files"])}')
    print('Installed now:', ', '.join(MISSING_INSTALLED) or 'nothing (all libraries present)')
    print(f'Working project: {os.path.relpath(PROJECT)} | figures saved: {len(figures)}/{EXPECTED_FIGURES}')
