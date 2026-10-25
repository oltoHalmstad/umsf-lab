"""Time helpers: UTC storage (ISO-8601 with ``Z``) and Europe/Kyiv display."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
DISPLAY_TZ_NAME = "Europe/Kyiv"
_ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")


def _load_display_tz():
    try:
        from zoneinfo import ZoneInfo

        try:
            return ZoneInfo(DISPLAY_TZ_NAME)
        except Exception:  # pragma: no cover - old tzdata
            return ZoneInfo("Europe/Kiev")
    except Exception:  # pragma: no cover - no tz database (e.g. Windows w/o tzdata)
        return None


_KYIV = _load_display_tz()


def is_iso_z(value) -> bool:
    """True for a real calendar instant formatted ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z``."""
    if not (isinstance(value, str) and _ISO_Z.match(value)):
        return False
    try:
        datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 UTC string ending in ``Z`` into an aware datetime."""
    if not is_iso_z(value):
        raise ValueError(f"not an ISO-8601 UTC 'Z' timestamp: {value!r}")
    base, _, frac = value[:-1].partition(".")
    dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")  # portable across Python 3.10+
    return dt.replace(microsecond=int(frac.ljust(6, "0")) if frac else 0, tzinfo=UTC)


def fmt_iso(dt: datetime) -> str:
    """Format an aware datetime as ISO-8601 UTC with ``Z`` (ms precision if needed)."""
    dt = dt.astimezone(UTC)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_epoch(value: str) -> float:
    return parse_iso(value).timestamp()


def from_epoch(ts: float) -> str:
    return fmt_iso(datetime.fromtimestamp(round(ts, 3), tz=UTC))


def _last_sunday(year: int, month: int) -> datetime:
    d = datetime(year, month + 1, 1, tzinfo=UTC) - timedelta(days=1) if month < 12 else datetime(year, 12, 31, tzinfo=UTC)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def to_kyiv(value) -> str:
    """Return an ISO string in Europe/Kyiv local time (display only; never stored as truth)."""
    dt = parse_iso(value) if isinstance(value, str) else value.astimezone(UTC)
    if _KYIV is not None:
        return dt.astimezone(_KYIV).isoformat(timespec="seconds")
    # Fallback: EU DST rule (EET +02:00 / EEST +03:00), switch at 01:00 UTC.
    start = _last_sunday(dt.year, 3).replace(hour=1)
    end = _last_sunday(dt.year, 10).replace(hour=1)
    off = 3 if start <= dt < end else 2
    return dt.astimezone(timezone(timedelta(hours=off))).isoformat(timespec="seconds")
