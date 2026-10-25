"""Append-only, hash-chained JSONL audit log.

Each entry carries `seq`, `prev_hash` and `entry_hash` (SHA-256 over the
canonical entry without `entry_hash`). The chain detects edits or deletions
of earlier lines; it is an integrity aid, not a signature (no key is involved).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .util import canonical_json, fmt_ts, sha256_text

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, path: str):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        self._seq, self._last = self._tail()

    def _tail(self) -> Tuple[int, str]:
        if not os.path.exists(self.path):
            return 0, GENESIS
        seq, last = 0, GENESIS
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    e = json.loads(line)
                    seq, last = e.get("seq", seq), e.get("entry_hash", last)
        return seq, last

    def append(self, entry_type: str, payload: Dict[str, Any], scenario_time: Optional[str] = None) -> Dict[str, Any]:
        self._seq += 1
        entry = {
            "seq": self._seq,
            "entry_type": entry_type,
            "recorded_at": fmt_ts(datetime.now(timezone.utc)),
            "scenario_time": scenario_time,
            "payload": payload,
            "prev_hash": self._last,
        }
        entry["entry_hash"] = sha256_text(canonical_json(entry))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._last = entry["entry_hash"]
        return entry

    def entries(self) -> Iterator[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return iter(())
        with open(self.path, "r", encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        return iter(rows)


def verify_chain(path: str) -> Tuple[bool, List[str]]:
    problems: List[str] = []
    prev = GENESIS
    expect = 1
    if not os.path.exists(path):
        return False, ["audit log missing"]
    with open(path, "r", encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            if not line.strip():
                continue
            e = json.loads(line)
            h = e.pop("entry_hash", None)
            if e.get("seq") != expect:
                problems.append(f"line {ln}: seq {e.get('seq')} != {expect}")
            if e.get("prev_hash") != prev:
                problems.append(f"line {ln}: prev_hash mismatch")
            if sha256_text(canonical_json(e)) != h:
                problems.append(f"line {ln}: entry_hash mismatch")
            prev = h
            expect += 1
    return not problems, problems
