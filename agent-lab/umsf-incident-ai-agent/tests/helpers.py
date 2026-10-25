"""Shared test helpers: a generated synthetic scenario cached per process."""

import atexit
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from umsf_agent.scenario import generate  # noqa: E402

_DIR = None


def scenario_dir() -> str:
    global _DIR
    if _DIR is None:
        _DIR = tempfile.mkdtemp(prefix="umsf_p3_test_")
        atexit.register(shutil.rmtree, _DIR, True)
        generate(os.path.join(_DIR, "scn"))
    return os.path.join(_DIR, "scn")


def tmpdir() -> str:
    d = tempfile.mkdtemp(prefix="umsf_p3_out_")
    atexit.register(shutil.rmtree, d, True)
    return d


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def read_json(path: str):
    import json
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_jsonl(path: str):
    import json
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]
