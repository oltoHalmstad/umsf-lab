"""UMSF Incident AI Agent Laboratory runtime (notebook release 1.2.0).

Written to disk by the notebook's setup section and imported by every analysis cell with
``from umsf_ai_lab import *``. Importing it is idempotent and cheap after the first time:

* installs only missing plotting libraries;
* verifies the embedded payload (``umsf_ai_payload.py``, an xz-compressed tar) and all 77 original
  source/fixture hashes, and extracts the project once into ``umsf_agent_runs/project`` (reused while it
  verifies);
* defines plotting conventions and output helpers;
* exposes lazily computed, cached states: the original test suite, supplied analytical checks, the
  ingested scenario, both chronological agent replays and the verification ledger.

Because each shared state is built on first use, any analysis cell can run on its own, in any order, and
after a kernel restart. Independent heavy work runs in parallel subprocesses: the ten original test
modules and the no-backup replay. The original agent 1.0.0 source is never modified.
"""
from __future__ import annotations

import base64, functools, hashlib, html, importlib.util, io, json, os, platform, re, shutil, subprocess
import sys, tarfile, textwrap, time, zipfile
from pathlib import Path
from types import SimpleNamespace

NOTEBOOK_RELEASE = '1.2.0'
AGENT_RELEASE = '1.0.0'
assert sys.version_info >= (3, 10), 'Python 3.10 or later is required.'

# ---------------------------------------------------------------- 1. dependencies
REQUIREMENTS = {'numpy': 'numpy>=1.24,<3', 'pandas': 'pandas>=2,<4', 'matplotlib': 'matplotlib>=3.9,<4'}
MISSING_INSTALLED = [req for mod, req in REQUIREMENTS.items() if importlib.util.find_spec(mod) is None]
if MISSING_INSTALLED:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', *MISSING_INSTALLED])
    importlib.invalidate_caches()

# ---------------------------------------------------------------- 2. verified project
RUNS = Path.cwd() / 'umsf_agent_runs'
RUN = RUNS / 'project'
_MARKER = RUN / '.payload_sha256'


def _verify_sources(root: Path) -> dict:
    expected = json.loads((root / 'provenance/source_sha256.json').read_text())
    for name, digest in expected.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise AssertionError(f'Original source/fixture file changed: {name}')
    return expected


def _prepare_project():
    from umsf_ai_payload import PAYLOAD, PAYLOAD_SHA256
    if _MARKER.exists() and _MARKER.read_text().strip() == PAYLOAD_SHA256:
        try:
            return PAYLOAD_SHA256, _verify_sources(RUN), 'reused'
        except (AssertionError, OSError):
            pass  # damaged or edited copy: extract again below
    blob = base64.b85decode(''.join(PAYLOAD.split()))
    assert hashlib.sha256(blob).hexdigest() == PAYLOAD_SHA256, 'Embedded payload checksum mismatch.'
    staging = RUNS / '.staging'
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:xz') as archive:
        members = archive.getmembers()
        for m in members:
            assert m.isfile() and (staging / m.name).resolve().is_relative_to(staging.resolve()), 'Unsafe archive entry.'
        archive.extractall(staging, members=members, **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))
    expected = _verify_sources(staging)
    shutil.rmtree(RUN, ignore_errors=True)
    staging.rename(RUN)
    _MARKER.write_text(PAYLOAD_SHA256)
    return PAYLOAD_SHA256, expected, 'extracted'


PAYLOAD_SHA256, EXPECTED_SOURCES, PROJECT_STATUS = _prepare_project()
CORE = RUN / 'umsf-incident-ai-agent'
DATA = CORE / 'examples/scenario_post_impact'
DATA_NO_BACKUP = CORE / 'examples/scenario_no_backup_power'
OUT = RUN / 'results'
FIG = OUT / 'figures'
FIG.mkdir(parents=True, exist_ok=True)
if str(CORE / 'src') not in sys.path:
    sys.path.insert(0, str(CORE / 'src'))

# ---------------------------------------------------------------- 3. libraries and conventions
import numpy as np, pandas as pd, matplotlib
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
from IPython.display import display, HTML, Markdown

from umsf_agent.agent import Agent
from umsf_agent.util import parse_ts

COLORS = ['#087E8B', '#E79535', '#6C60A8', '#BD4C67', '#659760', '#446A8C']
plt.rcParams.update({'figure.figsize': (10, 4.7), 'figure.dpi': 110, 'font.size': 11, 'axes.spines.top': False,
                     'axes.spines.right': False, 'axes.grid': True, 'grid.alpha': .18, 'svg.fonttype': 'none',
                     'axes.titleweight': 'bold', 'axes.prop_cycle': matplotlib.cycler(color=COLORS),
                     'svg.hashsalt': 'umsf-ai'})
EXPECTED_FIGURES = 30
REPLAY_TIMES = pd.date_range('2026-10-14T08:30:00Z', '2026-10-14T09:10:00Z', freq='1min')


def newfig(*a, **kw):
    return plt.subplots(*a, layout='constrained', **kw)


def figure_index() -> list:
    path = OUT / 'figure_index.json'
    return json.loads(path.read_text()) if path.exists() else []


def save(name, fig=None):
    """Save the current figure as PNG + SVG, register it in the persistent index and show it."""
    fig = fig or plt.gcf()
    fig.savefig(FIG / f'{name}.png', dpi=180, bbox_inches='tight')
    fig.savefig(FIG / f'{name}.svg', bbox_inches='tight', metadata={'Date': None})
    (OUT / 'figure_index.json').write_text(json.dumps(sorted(set(figure_index()) | {name}), indent=2) + '\n')
    plt.show()
    plt.close(fig)


def savejson(name, obj, compact=False):
    text = json.dumps(obj, ensure_ascii=False, default=str, **({'separators': (',', ':')} if compact else {'indent': 2}))
    (OUT / name).write_text(text + '\n')


def _rel(path) -> str:
    """Path relative to the working directory, so recorded outputs carry no machine-specific prefix."""
    return os.path.relpath(path)


def human(s):
    return str(s).replace('_', ' ').replace('RT-', '').replace('RC-', '')


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
                print(f'[umsf_ai_lab] {label} ready in {time.perf_counter() - started:.1f} s')
            return value
        inner.cache_clear = cached.cache_clear
        return inner
    return wrap


@functools.cache
def versions() -> dict:
    return {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__,
            'matplotlib': matplotlib.__version__}


# ---------------------------------------------------------------- 4. background jobs
_JOBS: dict = {}
_ENV = {**os.environ, 'PYTHONPATH': os.pathsep.join(filter(None, [str(CORE / 'src'), os.environ.get('PYTHONPATH')]))}
_NO_BACKUP_SCRIPT = textwrap.dedent('''
    import json, sys
    import pandas as pd
    from umsf_agent.agent import Agent
    data, out, dest = sys.argv[1:4]
    agent = Agent(data, out, use_llm=False)
    times = pd.date_range('2026-10-14T08:30:00Z', '2026-10-14T09:10:00Z', freq='1min')
    last = [agent.step(t.to_pydatetime()) for t in times][-1]
    with open(dest, 'w', encoding='utf-8') as fh:
        json.dump({'timeline': agent.timeline, 'last_status': last['continuity']['result']['status'],
                   'snapshots': len(times)}, fh, ensure_ascii=False, default=str)
''')


def _launch(name, cmd, cwd):
    """Start a subprocess once per kernel session; later calls return the same job."""
    if name not in _JOBS:
        _JOBS[name] = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=_ENV, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return _JOBS[name]


_RESULTS: dict = {}


def _wait(name):
    """Wait for a job once and remember its (return code, output)."""
    if name not in _RESULTS:
        output, _ = _JOBS[name].communicate()
        _RESULTS[name] = (_JOBS[name].returncode, output)
    return _RESULTS[name]


def _start_no_backup():
    shutil.rmtree(OUT / 'no_backup_run', ignore_errors=True)  # fresh audit chain on every replay
    # Paths relative to the project keep machine-specific directories out of the recorded outputs.
    _launch('no_backup', [sys.executable, '-c', _NO_BACKUP_SCRIPT, DATA_NO_BACKUP.relative_to(RUN),
                          (OUT / 'no_backup_run').relative_to(RUN), (OUT / '.no_backup_result.json').relative_to(RUN)], RUN)


# ---------------------------------------------------------------- 5. lazily computed states
@_timed('Original test suite (10 modules in parallel)')
def original_tests() -> SimpleNamespace:
    """All original test modules run concurrently as separate unittest processes; zero skips required."""
    if 'no_backup' not in _JOBS:
        _start_no_backup()  # independent replay overlaps with the tests
    modules = sorted(p.stem for p in (CORE / 'tests').glob('test_*.py'))
    for m in modules:
        _launch(f'test:{m}', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', f'{m}.py', '-v'], CORE)
    logs, failed, total = [], [], 0
    for m in modules:
        code, output = _wait(f'test:{m}')
        logs.append(f'===== {m} =====\n{output}')
        total += int(re.search(r'Ran (\d+) tests?', output).group(1))
        if code:
            failed.append(m)
    log = '\n'.join(logs) + f'\n===== SUMMARY =====\nRan {total} tests in {len(modules)} parallel module processes\n'
    log += 'FAILED: ' + ', '.join(failed) + '\n' if failed else 'OK\n'
    (OUT / 'original_tests.log').write_text(log)
    if failed:
        print(log)
        raise AssertionError(f'Original tests failed in: {failed}')
    assert 'skipped=' not in log and '... skipped' not in log
    return SimpleNamespace(log=log, n_tests=total, modules=re.findall(r'\((test_\w+)\.', log))


@_timed('Supplied analytical checks')
def paper_checks() -> SimpleNamespace:
    from umsf_agent.paper import checks, table10_case
    from umsf_agent.continuity import fig14_table
    paper = checks()
    assert all(x['pass'] for x in paper)
    savejson('analytical_checks.json', paper)
    cases = []
    for name in 'ABC':
        g, d = table10_case(name)
        cases.append({'case': name, 'expected': g.N, 'eligible': g.n, 'flagged': g.m, 'coverage_pct': g.C_pct,
                      'flagged_pct': g.p_pct, 'group_trigger': g.A, 'interpretation': d.label_en})
    case_df, front = pd.DataFrame(cases), pd.DataFrame(fig14_table())
    case_df.to_csv(OUT / 'paper_cases.csv', index=False)
    front.to_csv(OUT / 'continuity_frontier.csv', index=False)
    return SimpleNamespace(paper=paper, case_df=case_df, front=front)


@_timed('Scenario ingestion')
def dataset():
    from umsf_agent.ingest import load_dataset
    return load_dataset(_rel(DATA))


@_timed('Chronological agent replay (41 cutoffs)')
def replay() -> SimpleNamespace:
    """Original Agent.step at one-minute cutoffs 08:30-09:10 UTC; proposals only, no approvals."""
    shutil.rmtree(OUT / 'agent_run', ignore_errors=True)  # fresh audit chain on every replay
    agent = Agent(_rel(DATA), _rel(OUT / 'agent_run'), use_llm=False, auto_approve=False)
    snapshots = [agent.step(t.to_pydatetime()) for t in REPLAY_TIMES]
    tl = pd.DataFrame(agent.timeline)
    tl['minute'] = (pd.to_datetime(tl.as_of) - REPLAY_TIMES[0]).dt.total_seconds() / 60
    res = snapshots[30]  # 09:00 UTC, a representative planning snapshot
    savejson('snapshots.json', snapshots, compact=True)
    savejson('timeline.json', agent.timeline)
    savejson('raw_snapshot_0900.json', res)
    packages = list(agent.current_packages.values())
    savejson('raw_decision_packages.json', packages)
    tl.drop(columns=['personnel_counts', 'group_states', 'changed_domains']).to_csv(OUT / 'timeline.csv', index=False)
    recovery = pd.DataFrame(res['recovery']['tasks'])
    recovery.drop(columns=['title_uk'], errors='ignore').to_csv(OUT / 'recovery_schedule.csv', index=False)
    return SimpleNamespace(agent=agent, snapshots=snapshots, tl=tl, res=res, packages=packages,
                           cont=res['continuity']['result'], assign=pd.DataFrame(res['rescue']['assignments']),
                           recovery=recovery, scheduled=recovery[recovery.status == 'scheduled_candidate'].copy())


@_timed('No-backup scenario replay (background process)')
def replay_no_backup() -> SimpleNamespace:
    if 'no_backup' not in _JOBS:
        _start_no_backup()
    code, output = _wait('no_backup')
    if code:
        print(output)
        raise RuntimeError('No-backup replay failed')
    result = json.loads((OUT / '.no_backup_result.json').read_text())
    (OUT / '.no_backup_result.json').unlink()
    savejson('no_backup_timeline.json', result['timeline'])
    return SimpleNamespace(tl=pd.DataFrame(result['timeline']), last_status=result['last_status'],
                           snapshots=result['snapshots'])


def verification() -> dict:
    """Verification ledger: cached checks plus the current figure count, written to disk."""
    assert _verify_sources(RUN) == EXPECTED_SOURCES
    t, p, r = original_tests(), paper_checks(), replay()
    ledger = {'status': 'PASS', 'original_tests': t.n_tests, 'skipped_tests': 0, 'analytical_checks': len(p.paper),
              'figures': len(figure_index()), 'replay_snapshots_per_variant': len(r.snapshots),
              'source_and_fixture_files_verified': len(EXPECTED_SOURCES), 'synthetic_data': True,
              'external_llm_called': False, 'hosted_colab_session_tested': False, 'operationally_validated': False,
              'versions': versions()}
    savejson('verification.json', ledger)
    return ledger


def status() -> None:
    """Print a one-screen summary of the runtime and outputs produced so far."""
    v = versions()
    print(f'UMSF Incident AI Agent Laboratory {NOTEBOOK_RELEASE} | agent {AGENT_RELEASE} | Python {v["python"]}')
    print(f'Payload {PAYLOAD_SHA256[:16]}… {PROJECT_STATUS}; source/fixture files verified: {len(EXPECTED_SOURCES)}')
    print('Installed now:', ', '.join(MISSING_INSTALLED) or 'nothing (all libraries present)')
    print(f'Working project: {os.path.relpath(RUN)} | figures saved: {len(figure_index())}/{EXPECTED_FIGURES}')
