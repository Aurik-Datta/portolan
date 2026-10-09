"""Infer JSON Schema from observed values, and merge schemas across samples.

The rule of thumb: a field is `required` only if every sample had it, and a
field's type widens to cover everything seen. More samples, better schemas.
"""

from __future__ import annotations

import re
from typing import Any

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _string_format(value: str) -> str | None:
    if UUID.match(value):
        return "uuid"
    if DATETIME.match(value):
        return "date-time"
    if DATE.match(value):
        return "date"
    if EMAIL.match(value):
        return "email"
    return None


def infer(value: Any) -> dict[str, Any]:
    """Schema for a single observed value."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        schema: dict[str, Any] = {"type": "string"}
        fmt = _string_format(value)
        if fmt:
            schema["format"] = fmt
        return schema
    if isinstance(value, list):
        items: dict[str, Any] | None = None
        for item in value:
            items = infer(item) if items is None else merge(items, infer(item))
        return {"type": "array", "items": items or {}}
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {k: infer(v) for k, v in value.items()},
            "required": sorted(value.keys()),
        }
    return {}


def _types(schema: dict[str, Any]) -> set[str]:
    t = schema.get("type")
    if t is None:
        return set()
    return set(t) if isinstance(t, list) else {t}


def merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Least-general schema covering both inputs."""
    if not a:
        return dict(b)
    if not b:
        return dict(a)
    types = _types(a) | _types(b)
    if types == {"integer", "number"}:
        types = {"number"}
    out: dict[str, Any] = {}

    if "object" in types and a.get("type") == b.get("type") == "object":
        props_a, props_b = a.get("properties", {}), b.get("properties", {})
        props = {}
        for key in props_a.keys() | props_b.keys():
            if key in props_a and key in props_b:
                props[key] = merge(props_a[key], props_b[key])
            else:
                props[key] = dict(props_a.get(key) or props_b[key])
        out["properties"] = dict(sorted(props.items()))
        out["required"] = sorted(set(a.get("required", [])) & set(b.get("required", [])))
    elif "array" in types and a.get("type") == b.get("type") == "array":
        out["items"] = merge(a.get("items", {}), b.get("items", {}))
    else:
        for side in (a, b):
            for key in ("properties", "required", "items"):
                if key in side and key not in out:
                    out[key] = side[key]

    fmt_a, fmt_b = a.get("format"), b.get("format")
    if fmt_a and fmt_a == fmt_b:
        out["format"] = fmt_a

    out["type"] = sorted(types)[0] if len(types) == 1 else sorted(types)
    return dict(sorted(out.items()))


def infer_many(values: list[Any]) -> dict[str, Any]:
    schema: dict[str, Any] = {}
    for v in values:
        schema = merge(schema, infer(v))
    return schema


def infer_scalar_from_strings(values: list[str]) -> dict[str, Any]:
    """Query strings arrive as text; recover ints and booleans where every sample agrees."""
    if values and all(re.fullmatch(r"-?\d+", v) for v in values):
        return {"type": "integer"}
    if values and all(v.lower() in {"true", "false"} for v in values):
        return {"type": "boolean"}
    return {"type": "string"}


def summarize(schema: dict[str, Any], limit: int = 8) -> str:
    """Short human description of a response schema, for tool descriptions."""
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        if set(props) == {"items"} or ("items" in props and props["items"].get("type") == "array"):
            inner = props["items"].get("items", {})
            fields = list(inner.get("properties", {}))[:limit]
            extra = [k for k in props if k != "items"]
            tail = f" (plus {', '.join(extra)})" if extra else ""
            return f"a list of objects with fields: {', '.join(fields)}{tail}"
        fields = list(props)[:limit]
        return f"an object with fields: {', '.join(fields)}" if fields else "an object"
    if schema.get("type") == "array":
        return "a list"
    return str(schema.get("type", "unknown"))
