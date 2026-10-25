"""Small shared helpers: UTC time handling, canonical JSON, hashing."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

UTC = timezone.utc


def parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp to an aware UTC datetime.

    Returns None for null/empty/unparseable values: an unknown time stays
    unknown rather than being replaced by a guess.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_ts(dt: Optional[datetime]) -> Optional[str]:
    """Format an aware datetime as ISO-8601 UTC with 'Z' (seconds precision)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_s(dt: datetime, seconds: float) -> datetime:
    return dt + timedelta(seconds=seconds)


def age_s(now: datetime, then: Optional[datetime]) -> Optional[float]:
    if then is None:
        return None
    return (now - then).total_seconds()


def canonical_json(obj: Any) -> str:
    """Deterministic JSON serialisation used for hashing."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      default=_json_default)


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return fmt_ts(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if hasattr(o, "to_dict"):
        return o.to_dict()
    raise TypeError(f"not JSON serialisable: {type(o)!r}")


def dumps(obj: Any, indent: int = 2) -> str:
    return json.dumps(obj, sort_keys=False, ensure_ascii=False, indent=indent,
                      default=_json_default)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_obj(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def median(values: Iterable[float]) -> Optional[float]:
    v = sorted(values)
    n = len(v)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return float(v[mid])
    return (v[mid - 1] + v[mid]) / 2.0


def pct(num: int, den: int, digits: int = 1) -> Optional[float]:
    """Percentage rounded half-up to `digits`; None if denominator is zero."""
    if not den:
        return None
    q = 100.0 * num / den
    f = 10 ** digits
    return math.floor(q * f + 0.5) / f


def ceil_frac(numerator_frac: float, n: int) -> int:
    """ceil(frac * n) robust against binary floating error (e.g. 0.7*10)."""
    x = numerator_frac * n
    r = round(x)
    if abs(x - r) < 1e-9:
        return int(r)
    return int(math.ceil(x))
