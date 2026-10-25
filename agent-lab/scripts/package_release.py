"""Validate the release and package it for Zenodo with a SHA-256 inventory (run after execute_notebook.py)."""
from pathlib import Path
import hashlib, json, zipfile
import nbformat

root = Path(__file__).resolve().parents[1]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
original = json.loads((root / 'provenance/source_sha256.json').read_text())
for name, digest in original.items():
    assert sha(root / name) == digest, f'Original source/fixture file changed: {name}'
clean = nbformat.read(root / 'UMSF_AI_Agent_Lab.ipynb', as_version=4)
executed = nbformat.read(root / 'UMSF_AI_Agent_Lab_executed.ipynb', as_version=4)
nbformat.validate(clean); nbformat.validate(executed)
assert [c.source for c in clean.cells] == [c.source for c in executed.cells]
assert all(c.execution_count is not None for c in executed.cells if c.cell_type == 'code')
assert not [o for c in executed.cells if c.cell_type == 'code' for o in c.outputs if o.output_type == 'error']
lab = next(c.source for c in clean.cells if c.cell_type == 'code' and c.source.startswith('%%writefile umsf_ai_lab.py'))
assert lab.split('\n', 1)[1].strip() == (root / 'notebook/umsf_ai_lab.py').read_text().strip(), 'runtime cell differs'
report = json.loads((root / 'results/VALIDATION_REPORT.json').read_text())
code_cells = sum(c.cell_type == 'code' for c in clean.cells)
assert report['status'] == 'PASS' and report['code_cells_executed'] == code_cells == 31
assert report['cell_self_sufficiency']['performed'] and report['cell_self_sufficiency']['cells_failed'] == 0
assert report['cell_self_sufficiency']['cells_checked'] == code_cells - 3
assert report['verification']['figures'] == 30
assert len(list((root / 'figures').glob('*.png'))) == len(list((root / 'figures').glob('*.svg'))) == 30
skip = {'__pycache__', 'build', '.pio'}
files = [p for p in sorted(root.rglob('*')) if p.is_file() and not skip & set(p.relative_to(root).parts)
         and p.name != 'SHA256SUMS.txt']
lines = [sha(p) + '  ' + p.relative_to(root).as_posix() for p in files]
(root / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n')
files.append(root / 'SHA256SUMS.txt')
dest = root.parent / (root.name + '-zenodo.zip')
with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for p in sorted(files):
        info = zipfile.ZipInfo((Path(root.name) / p.relative_to(root)).as_posix(), date_time=(2026, 10, 14, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, p.read_bytes())
with zipfile.ZipFile(dest) as archive:
    assert archive.testzip() is None
    for line in lines:
        digest, name = line.split('  ', 1)
        assert hashlib.sha256(archive.read(root.name + '/' + name)).hexdigest() == digest
print(json.dumps({'file': str(dest), 'bytes': dest.stat().st_size, 'entries': len(files), 'sha256': sha(dest),
                  'original_files_preserved': len(original), 'all_archive_hashes_verified': True}, indent=2))
