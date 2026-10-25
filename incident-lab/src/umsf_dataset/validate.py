"""Pure-Python validation of UMSF JSON records (bounded parsing + JSON-Schema subset).

The schema files in ``umsf_dataset/schemas`` are authoritative; this module
interprets the subset of JSON Schema they use (type, const, enum, minimum,
maximum, minLength, maxLength, pattern, format=date-time, required,
properties, additionalProperties, items, minItems, maxItems, maxProperties).

Rejections (Study B, Table 12): malformed JSON, NaN/Infinity, unknown fields,
type and range errors, and ``data_origin == "measured"`` unless explicitly
allowed (the measured/synthetic label is not cryptographic proof, but test
pipelines must not accept records that claim to be real human data).
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from importlib import resources

from .timeutil import is_iso_z

MAX_LINE_BYTES = 8192
MAX_DEPTH = 6
SCHEMA_FILES = {"1.0": "physio-1.0.schema.json", "st-1.0": "station-st-1.0.schema.json",
                "ev-1.0": "event-ev-1.0.schema.json", "roster": "roster.schema.json"}
KIND_BY_VERSION = {"1.0": "physio", "st-1.0": "station", "ev-1.0": "event"}


class ParseError(ValueError):
    pass


@lru_cache(maxsize=None)
def load_schema(version: str) -> dict:
    name = SCHEMA_FILES[version]
    return json.loads(resources.files("umsf_dataset").joinpath("schemas", name).read_text(encoding="utf-8"))


def _reject_constant(name):
    raise ParseError(f"non-finite number {name} not allowed")


def _finite_float(s):
    v = float(s)
    if not math.isfinite(v):
        raise ParseError(f"non-finite number {s} not allowed")
    return v


def _no_dupes(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ParseError(f"duplicate key {k!r}")
        obj[k] = v
    return obj


def _depth(o, d=0):
    if d > MAX_DEPTH:
        raise ParseError("nesting too deep")
    if isinstance(o, dict):
        for v in o.values():
            _depth(v, d + 1)
    elif isinstance(o, list):
        for v in o:
            _depth(v, d + 1)


def parse_json_line(line, max_bytes: int = MAX_LINE_BYTES) -> dict:
    """Bounded, strict parse of one JSONL line into an object. Raises ParseError."""
    raw = line.encode("utf-8") if isinstance(line, str) else bytes(line)
    if len(raw) > max_bytes:
        raise ParseError(f"line exceeds {max_bytes} bytes")
    try:
        obj = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant, parse_float=_finite_float,
                         object_pairs_hook=_no_dupes)
    except ParseError:
        raise
    except (ValueError, UnicodeDecodeError) as exc:
        raise ParseError(f"malformed JSON: {exc}") from None
    if not isinstance(obj, dict):
        raise ParseError("top-level JSON value must be an object")
    _depth(obj)
    return obj


_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}


def check_schema(value, schema: dict, path: str = "$") -> list[str]:
    """Validate ``value`` against a schema dict; returns a list of error strings."""
    errs: list[str] = []
    if "const" in schema and value != schema["const"]:
        return [f"{path}: expected {schema['const']!r}"]
    if "enum" in schema and not any(value == e and type(value) is type(e) for e in schema["enum"]):
        return [f"{path}: {value!r} not in allowed values"]
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in types):
            return [f"{path}: invalid type {type(value).__name__}"]
    if isinstance(value, float) and not math.isfinite(value):
        return [f"{path}: non-finite number"]
    if _TYPES["number"](value):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} above maximum {schema['maximum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 1 << 30):
            errs.append(f"{path}: string length out of range")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: does not match pattern")
        if schema.get("format") == "date-time" and not is_iso_z(value):
            errs.append(f"{path}: not an ISO-8601 UTC timestamp ending in Z")
    if isinstance(value, dict):
        if len(value) > schema.get("maxProperties", 1 << 30):
            errs.append(f"{path}: too many properties")
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}.{k}: missing required field")
        addl = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                errs += check_schema(v, props[k], f"{path}.{k}")
            elif addl is False:
                errs.append(f"{path}.{k}: unknown field")
            elif isinstance(addl, dict):
                errs += check_schema(v, addl, f"{path}.{k}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 1 << 30):
            errs.append(f"{path}: array length out of range")
        if "items" in schema:
            for i, v in enumerate(value):
                errs += check_schema(v, schema["items"], f"{path}[{i}]")
    return errs


def validate_record(obj: dict, allow_measured: bool = False) -> tuple[str | None, list[str]]:
    """Return ``(kind, errors)`` where kind is physio/station/event (None if unknown schema)."""
    version = obj.get("schema_version")
    kind = KIND_BY_VERSION.get(version) if isinstance(version, str) else None
    if kind is None:
        return None, [f"$.schema_version: unsupported {version!r}"]
    errs = check_schema(obj, load_schema(version))
    if obj.get("data_origin") == "measured" and not allow_measured:
        errs.append("$.data_origin: 'measured' rejected (use --allow-measured with an approved protocol)")
    if kind == "event" and obj.get("event_type") == "external_strike_report" \
            and obj.get("source_class") != "authoritative_external_alert":
        errs.append("$.event_type: external_strike_report only from an authoritative_external_alert source")
    return kind, errs


def validate_line(line, allow_measured: bool = False, max_bytes: int = MAX_LINE_BYTES):
    """Parse + validate one line. Returns ``(kind, obj, errors)``; obj is None if unparseable."""
    try:
        obj = parse_json_line(line, max_bytes)
    except ParseError as exc:
        return None, None, [str(exc)]
    kind, errs = validate_record(obj, allow_measured)
    return kind, obj, errs


def validate_roster(obj: dict) -> list[str]:
    errs = check_schema(obj, load_schema("roster"))
    if not errs:
        workers = {w for z in obj["zones"] for w in z["expected_workers"]}
        nodes = {n for z in obj["zones"] for n in z["stationary_nodes"]}
        if workers & nodes:
            errs.append("$.zones: an identifier is listed both as worker and stationary node")
    return errs
