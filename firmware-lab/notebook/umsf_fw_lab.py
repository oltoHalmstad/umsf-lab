"""UMSF Firmware Laboratory runtime (notebook release 1.2.0).

Written to disk by the notebook's setup section and imported by every analysis cell with
``from umsf_fw_lab import *``. Importing it is idempotent and cheap after the first time:

* installs only missing Python libraries and checks for gcc/g++/make;
* verifies the embedded payload (``umsf_fw_payload.py``, an xz-compressed tar) and all original source hashes, and extracts
  the project once into ``umsf_firmware_runs/project`` (reused while it verifies);
* defines plotting conventions and output helpers;
* exposes lazily computed, cached native states: host tests, compiled C library, experiment CSVs,
  vector and corruption checks, and the verification ledger.

Because each shared state is built on first use, any analysis cell can run on its own, in any order, and
after a kernel restart. Native builds are incremental: unchanged binaries are reused. The original
firmware 1.0.0 sources are never modified.
"""
from __future__ import annotations

import base64, ctypes as ct, functools, hashlib, importlib.util, io, json, os, platform, re, shutil
import subprocess, sys, tarfile, time, zipfile
from pathlib import Path
from types import SimpleNamespace

NOTEBOOK_RELEASE = '1.2.0'
FIRMWARE_RELEASE = '1.0.0'
assert sys.version_info >= (3, 10), 'Python 3.10 or later is required.'

# ---------------------------------------------------------------- 1. dependencies
REQUIREMENTS = {'numpy': 'numpy>=1.24,<3', 'pandas': 'pandas>=2.0,<4', 'matplotlib': 'matplotlib>=3.7,<4'}
MISSING_INSTALLED = [req for mod, req in REQUIREMENTS.items() if importlib.util.find_spec(mod) is None]
if MISSING_INSTALLED:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', *MISSING_INSTALLED])
    importlib.invalidate_caches()
for _tool in ('gcc', 'g++', 'make'):
    if shutil.which(_tool) is None:
        raise RuntimeError(f'{_tool} missing: use a Linux CPU runtime or install build-essential.')

# ---------------------------------------------------------------- 2. verified project
RUNS = Path.cwd() / 'umsf_firmware_runs'
RUN = RUNS / 'project'
_MARKER = RUN / '.payload_sha256'


def _verify_sources(root: Path) -> dict:
    expected = json.loads((root / 'provenance/source_sha256.json').read_text())
    for name, digest in expected.items():
        if hashlib.sha256((root / 'firmware' / name).read_bytes()).hexdigest() != digest:
            raise AssertionError(f'Original firmware file changed: {name}')
    return expected


def _prepare_project():
    from umsf_fw_payload import PAYLOAD, PAYLOAD_SHA256
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
FW = RUN / 'firmware'
OUT = RUN / 'results'
FIG = OUT / 'figures'
BUILD = RUN / 'build'  # notebook-owned binaries; the original tree keeps only its own test/host/build
for _d in (OUT, FIG, BUILD):
    _d.mkdir(parents=True, exist_ok=True)

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
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from IPython.display import display, HTML, Markdown

plt.rcParams.update({'figure.figsize': (10, 4.6), 'figure.dpi': 110, 'axes.spines.top': False,
                     'axes.spines.right': False, 'axes.grid': True, 'grid.alpha': 0.18, 'font.size': 11,
                     'axes.titleweight': 'bold', 'svg.fonttype': 'none', 'savefig.facecolor': 'white',
                     'svg.hashsalt': 'umsf-fw'})
COLORS = ['#096B72', '#E98032', '#5665A6', '#B84C65', '#6C9457', '#7E6A9E']
plt.rcParams['axes.prop_cycle'] = matplotlib.cycler(color=COLORS)
EXPECTED_FIGURES = 30
JOBS = str(max(1, os.cpu_count() or 1))


def newfig(*args, **kwargs):
    return plt.subplots(*args, layout='constrained', **kwargs)


def figure_index() -> list:
    path = OUT / 'figure_index.json'
    return json.loads(path.read_text()) if path.exists() else []


def savefig(name, fig=None):
    """Save the current figure as PNG + SVG, register it in the persistent index and show it."""
    fig = fig or plt.gcf()
    fig.savefig(FIG / f'{name}.png', dpi=180, bbox_inches='tight')
    fig.savefig(FIG / f'{name}.svg', bbox_inches='tight', metadata={'Date': None})
    (OUT / 'figure_index.json').write_text(json.dumps(sorted(set(figure_index()) | {name}), indent=2) + '\n')
    plt.show()
    plt.close(fig)


def run_checked(cmd, cwd=None):
    r = subprocess.run([str(x) for x in cmd], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode:
        print(r.stdout)
        r.check_returncode()
    return r.stdout


def _stale(target: Path, sources) -> bool:
    """True when ``target`` is missing or older than any source (make-style incremental build)."""
    return not target.exists() or any(Path(s).stat().st_mtime > target.stat().st_mtime for s in sources)


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
                print(f'[umsf_fw_lab] {label} ready in {time.perf_counter() - started:.1f} s')
            return value
        inner.cache_clear = cached.cache_clear
        return inner
    return wrap


INCS = [f'-I{FW / "lib" / lib / "src"}' for lib in ('umsf_proto', 'umsf_features', 'umsf_buffer', 'umsf_gwcore')]
PROTO_C = sorted((FW / 'lib/umsf_proto/src').glob('*.c'))
HEADERS = sorted(p for lib in (FW / 'lib').iterdir() for p in (lib / 'src').glob('*.h'))


@functools.cache
def versions() -> dict:
    v = {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__,
         'matplotlib': matplotlib.__version__, 'platform': platform.platform(),
         'gcc': subprocess.check_output(['gcc', '--version'], text=True).splitlines()[0],
         'notebook_release': NOTEBOOK_RELEASE, 'firmware_release': FIRMWARE_RELEASE,
         'payload_sha256': PAYLOAD_SHA256}
    (OUT / 'versions.json').write_text(json.dumps(v, indent=2) + '\n')
    return v


# ---------------------------------------------------------------- 4. lazily built native states
def _start_shared_library():
    """Compile the original C protocol sources into a shared library (background process)."""
    shared = BUILD / 'libumsf.so'
    if not _stale(shared, PROTO_C + HEADERS):
        return shared, None
    cmd = ['gcc', '-std=c99', '-shared', '-fPIC', '-O2', *INCS, *map(str, PROTO_C), '-o', str(shared)]
    return shared, subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


_SHARED = None


@_timed('Original host tests (make)')
def native_tests() -> SimpleNamespace:
    """Build (parallel, incremental) and run the original 43-case host test suite."""
    global _SHARED
    _SHARED = _SHARED or _start_shared_library()  # independent build overlaps with make
    build = run_checked(['make', '--no-print-directory', '-C', 'test/host', f'-j{JOBS}', 'build/umsf_tests'], FW)
    log = build + run_checked(['make', '--no-print-directory', '-C', 'test/host', 'test'], FW)
    (OUT / 'native_tests.log').write_text(log)
    match = re.search(r'(\d+) test cases, (\d+) passed, (\d+) failed; (\d+) checks, (\d+) failed checks', log)
    assert match and match.group(1) == match.group(2) and match.group(3) == '0' and match.group(5) == '0'
    counts = dict(zip(['cases', 'passed', 'failed', 'checks', 'failed_checks'], map(int, match.groups())))
    return SimpleNamespace(log=log, counts=counts, names=re.findall(r'\[PASS\] (\w+)', log))


@_timed('Compiled original C library (ctypes)')
def native_lib() -> SimpleNamespace:
    """ctypes binding to the original CRC and BLE fragmentation functions."""
    global _SHARED
    shared, proc = _SHARED or _start_shared_library()
    _SHARED = (shared, None)
    if proc is not None:
        output, _ = proc.communicate()
        if proc.returncode:
            print(output)
            raise subprocess.CalledProcessError(proc.returncode, proc.args, output)
    native = ct.CDLL(str(shared))
    bytep = ct.POINTER(ct.c_uint8)
    native.umsf_crc16.argtypes = [bytep, ct.c_size_t]; native.umsf_crc16.restype = ct.c_uint16
    native.umsf_frag_count.argtypes = [ct.c_size_t, ct.c_size_t]; native.umsf_frag_count.restype = ct.c_uint
    native.umsf_frag_build.argtypes = [bytep, ct.c_size_t, ct.c_uint16, ct.c_uint, ct.c_size_t, bytep, ct.c_size_t]
    native.umsf_frag_build.restype = ct.c_size_t
    arr = lambda b: (ct.c_uint8 * len(b)).from_buffer_copy(b)  # noqa: E731
    crc = lambda b: native.umsf_crc16(arr(b), len(b))  # noqa: E731
    assert crc(b'123456789') == 0x29B1
    return SimpleNamespace(native=native, arr=arr, crc=crc, ct=ct)


@_timed('Native experiment harness')
def experiments() -> SimpleNamespace:
    """Compile lab/native_experiments.cpp against the original libraries, run it, load its CSVs."""
    tests = native_tests()  # provides the original umsf_proto object files
    del tests
    objects = sorted((FW / 'test/host/build/lib/umsf_proto/src').glob('*.o'))
    sources = [RUN / 'lab/native_experiments.cpp', FW / 'lib/umsf_features/src/umsf_features.cpp']
    exe = BUILD / 'native_experiments'
    if _stale(exe, sources + objects + HEADERS):
        run_checked(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', *INCS, *sources, *objects, '-o', exe])
    run_checked([exe, OUT])
    st = pd.read_csv(OUT / 'station.csv')
    st['baseline_mv'] = st.baseline_mv.replace(65535, np.nan)
    return SimpleNamespace(phys=pd.read_csv(OUT / 'physio.csv'), cases=pd.read_csv(OUT / 'physio_cases.csv'),
                           st=st, inp=pd.read_csv(OUT / 'station_input.csv'), events=pd.read_csv(OUT / 'events.csv'),
                           button=pd.read_csv(OUT / 'button.csv'), link=pd.read_csv(OUT / 'link.csv'),
                           buf=pd.read_csv(OUT / 'buffer.csv'), edge=pd.read_csv(OUT / 'buffer_edge.csv'))


@_timed('Protocol vectors')
def vector_check() -> SimpleNamespace:
    """Independent Python verifier plus the native CRC on every supplied vector."""
    log = run_checked([sys.executable, FW / 'tools/verify_vectors.py', FW / 'test_vectors.json'])
    (OUT / 'vector_verification.log').write_text(log)
    vectors = json.loads((FW / 'test_vectors.json').read_text())
    if isinstance(vectors, dict):
        vectors = vectors['vectors']
    crc = native_lib().crc
    rows = []
    for v in vectors:
        b = bytes.fromhex(v['hex'])
        rows.append({'name': v['name'], 'bytes': len(b), 'crc_valid': crc(b[:-2]) == int.from_bytes(b[-2:], 'little')})
    vdf = pd.DataFrame(rows)
    assert len(vdf) == 19 and vdf.crc_valid.sum() == 18
    return SimpleNamespace(log=log, vectors=vectors, vdf=vdf, first=bytes.fromhex(vectors[0]['hex']))


@_timed('Single-bit corruption experiment')
def mutation_check() -> list:
    first, crc = vector_check().first, native_lib().crc
    assert crc(first[:-2]) == int.from_bytes(first[-2:], 'little')
    rejected = []
    for bit in range(len(first) * 8):
        altered = bytearray(first)
        altered[bit // 8] ^= 1 << (bit % 8)
        rejected.append(crc(bytes(altered[:-2])) != int.from_bytes(altered[-2:], 'little'))
    assert all(rejected)
    return rejected


@_timed('Verification checks')
def _verified_checks() -> dict:
    t, x, v, rejected = native_tests(), experiments(), vector_check(), mutation_check()
    st = x.st
    assert len(x.phys) == 1155 and len(st) == 260
    assert 'possible_impact_local' in set(x.events.name)
    assert not ((st.query('time_s < 180')['flags'].to_numpy() & 16) > 0).any()
    assert st.query('time_s < 180').baseline_mv.isna().all()
    assert ((st.query('time_s > 95')['flags'].to_numpy() & 128) > 0).all()
    assert _verify_sources(RUN) == EXPECTED_SOURCES  # sources still unchanged after all builds
    ledger = {'status': 'PASS', 'original_native_tests': t.counts, 'supplied_vectors': len(v.vdf),
              'expected_bad_crc_vectors': int((~v.vdf.crc_valid).sum()),
              'single_bit_mutations_rejected': sum(rejected), 'physio_sweep_rows': len(x.phys),
              'station_windows': len(st), 'native_events': len(x.events),
              'source_files_unchanged': len(EXPECTED_SOURCES), 'esp32_images_compiled': False,
              'hardware_tested': False, 'hosted_colab_session_tested': False, 'synthetic_experiments_only': True,
              'versions': {k: versions()[k] for k in ('python', 'numpy', 'pandas', 'matplotlib', 'platform', 'gcc')}}
    return ledger


def verification() -> dict:
    """Verification ledger: cached native checks plus the current figure count, written to disk."""
    checks = _verified_checks()
    ledger = {**{k: checks[k] for k in list(checks)[:8]}, 'figures': len(figure_index()),
              **{k: checks[k] for k in list(checks)[8:]}}
    (OUT / 'verification.json').write_text(json.dumps(ledger, indent=2) + '\n')
    return ledger


def status() -> None:
    """Print a one-screen summary of the runtime and outputs produced so far."""
    v = versions()
    print(f'UMSF Firmware Laboratory {NOTEBOOK_RELEASE} | firmware {FIRMWARE_RELEASE} | Python {v["python"]}')
    print(f'Payload {PAYLOAD_SHA256[:16]}… {PROJECT_STATUS}; original source files verified: {len(EXPECTED_SOURCES)}')
    print('Installed now:', ', '.join(MISSING_INSTALLED) or 'nothing (all libraries present)', '|', v['gcc'])
    print(f'Working project: {os.path.relpath(RUN)} | figures saved: {len(figure_index())}/{EXPECTED_FIGURES}')
