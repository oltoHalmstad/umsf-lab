"""Command policy: defaults shipped with the package, overridable by incident command."""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, Optional

from .util import sha256_obj

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "data", "default_policy.json")


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def default_policy() -> Dict[str, Any]:
    with open(_DEFAULT_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_policy(path: Optional[str] = None, data_dir: Optional[str] = None) -> Dict[str, Any]:
    """Default policy, then `<data_dir>/policy.json` if present, then an explicit file."""
    pol = default_policy()
    sources = ["default"]
    for p in [os.path.join(data_dir, "policy.json") if data_dir else None, path]:
        if p and os.path.exists(p):
            with open(p, "r", encoding="utf-8") as fh:
                pol = _merge(pol, json.load(fh))
            sources.append(p)
    pol["_sources"] = sources
    pol["_sha256"] = sha256_obj({k: v for k, v in pol.items() if not k.startswith("_")})
    return pol
