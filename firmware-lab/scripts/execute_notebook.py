"""Execute the standalone notebook in a fresh kernel and directory, then (optionally) prove that every
analysis cell is self-sufficient: after the setup cells, each code cell runs alone in its own fresh
kernel, in reverse order. Writes the executed notebook, HTML report, figures, results and evidence."""
from pathlib import Path
import argparse, json, shutil, tempfile, time
import nbformat
from nbclient import NotebookClient
from nbconvert import HTMLExporter

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--kernel', default='python3', help='Jupyter kernel name')
parser.add_argument('--skip-isolation', action='store_true', help='skip the per-cell fresh-kernel check')
args = parser.parse_args()
source = root / 'UMSF_Firmware_Lab.ipynb'
nb = nbformat.read(source, as_version=4)
nbformat.validate(nb)
code_idx = [i for i, c in enumerate(nb.cells) if c.cell_type == 'code']
setup_idx = code_idx[:3]
assert all('%%writefile' in nb.cells[i].source for i in setup_idx[:2]) and 'umsf_fw_lab' in nb.cells[setup_idx[2]].source


def execute(notebook, workdir):
    started = time.perf_counter()
    NotebookClient(notebook, timeout=900, kernel_name=args.kernel, allow_errors=False,
                   resources={'metadata': {'path': str(workdir)}}).execute()
    return round(time.perf_counter() - started, 2)


# 1. Full sequential run ("Run all") in a fresh kernel and an empty directory.
work = Path(tempfile.mkdtemp(prefix='umsf-standalone-check-'))
shutil.copy2(source, work / source.name)
elapsed = execute(nb, work)
nbformat.write(nb, root / 'UMSF_Firmware_Lab_executed.ipynb')
code_cells = [nb.cells[i] for i in code_idx]
errors = [o for c in code_cells for o in c.outputs if o.output_type == 'error']
stderr = [o for c in code_cells for o in c.outputs if o.output_type == 'stream' and o.name == 'stderr']
assert not errors and not stderr and all(c.execution_count is not None for c in code_cells)
print(f'Run all: {len(code_cells)} code cells in {elapsed} s', flush=True)

project = work / 'umsf_firmware_runs/project'
results = project / 'results'
shutil.rmtree(root / 'results', ignore_errors=True)
shutil.rmtree(root / 'figures', ignore_errors=True)
shutil.copytree(results, root / 'results')
shutil.move(root / 'results/figures', root / 'figures')
(root / 'results/SHA256SUMS.txt').unlink()  # runtime paths differ after release assembly

# 2. Cell self-sufficiency: setup once, then each other code cell alone in a fresh kernel.
isolation = {'performed': False}
if not args.skip_isolation:
    iso = Path(tempfile.mkdtemp(prefix='umsf-isolation-check-'))
    clean = nbformat.read(source, as_version=4)

    def sub(indices):
        part = nbformat.v4.new_notebook(cells=[clean.cells[i] for i in indices])
        part.metadata = clean.metadata
        return part
    execute(sub(setup_idx), iso)
    rows = []
    for i in reversed(code_idx[3:]):
        seconds = execute(sub([i]), iso)
        rows.append({'cell_index': i, 'seconds': seconds})
        print(f'  isolated cell {i}: OK ({seconds} s)', flush=True)
    isolation = {'performed': True, 'method': 'setup cells once, then each code cell alone in a new kernel, '
                                              'reverse notebook order, shared working directory',
                 'cells_checked': len(rows), 'cells_failed': 0, 'cells': rows}

report = {'status': 'PASS', 'notebook_release': '1.2.0', 'notebook_cells': len(nb.cells),
          'code_cells_executed': len(code_cells), 'error_outputs': len(errors), 'stderr_outputs': len(stderr),
          'run_all_elapsed_seconds': elapsed, 'execution_engine': 'jupyter (nbclient)', 'fresh_kernel': True,
          'isolated_working_directory': True, 'only_notebook_supplied': True,
          'cell_self_sufficiency': isolation, 'hosted_google_colab_session_tested': False,
          'png_figures': len(list((root / 'figures').glob('*.png'))),
          'svg_figures': len(list((root / 'figures').glob('*.svg'))),
          'verification': json.loads((root / 'results/verification.json').read_text())}
(root / 'results/VALIDATION_REPORT.json').write_text(json.dumps(report, indent=2) + '\n')
exporter = HTMLExporter()
exporter.exclude_input_prompt = True
exporter.exclude_output_prompt = True
exporter.exclude_input = True  # the portable notebook remains the readable/runnable code source
body, _ = exporter.from_notebook_node(nb)
(root / 'UMSF_Firmware_Lab.html').write_text(body, encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if k not in ('verification',)}, indent=2)[:1500], flush=True)
