"""Compile recorded traffic into a typed operation catalog.

Pipeline:
    HAR -> filter to API calls -> templatize paths -> group into operations
        -> infer input/output schemas -> detect auth -> name + classify risk

Everything here is deterministic and LLM-free, so it is cheap to iterate on
against saved recordings. `naming.refine_with_llm` is an optional pass on top.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from portolan.catalog import AuthSpec, Catalog, Operation
from portolan.har import Exchange, filter_api, load_exchanges
from portolan.schema import infer_many, infer_scalar_from_strings, summarize

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
HEX = re.compile(r"^[0-9a-f]{16,}$", re.I)
DIGITS = re.compile(r"^\d+$")
# A digit alone doesn't make an id (v2beta, oauth2, 2fa-setup, x86_64): need a run of 3+ digits...
SLUGGY_ID = re.compile(r"^(?=.*\d{3})[A-Za-z0-9_.~-]{5,}$")  # POL-100234, DOC-100234-1, abc123xyz
# ...or a long random-looking token mixing cases and digits (nanoid, Firebase, YouTube-style ids).
RANDOM_ID = re.compile(r"^(?=(?:.*\d){2})(?=.*[a-z])(?=.*[A-Z])[A-Za-z0-9_-]{10,}$")
VERSION = re.compile(r"^v\d+(\.\d+)?$", re.I)

PREFIX_SEGMENTS = {"api", "rest", "services", "service", "internal", "graphql"}
IRREVERSIBLE = re.compile(
    r"(^|_)(bind|delete|cancel|submit|pay|purchase|issue|send|approve|finali[sz]e|terminate|void|refund|transfer)(_|$)"
)
SENSITIVE_KEY = re.compile(r"pass(word)?|secret|token|api[_-]?key|ssn|sin|card", re.I)


# ---------------------------------------------------------------- templating


def is_id_segment(segment: str) -> bool:
    if VERSION.match(segment):
        return False
    return bool(
        DIGITS.match(segment)
        or UUID.match(segment)
        or HEX.match(segment)
        or SLUGGY_ID.match(segment)
        or RANDOM_ID.match(segment)
    )


def singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _snake(word: str) -> str:
    word = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", word)
    return re.sub(r"[^a-zA-Z0-9]+", "_", word).strip("_").lower()


def templatize(path: str) -> tuple[str, list[str], list[str]]:
    """Return (template, param_names, observed_values) for a concrete path."""
    segments = [s for s in path.split("/") if s]
    out, names, values = [], [], []
    for i, seg in enumerate(segments):
        if is_id_segment(seg):
            prev = segments[i - 1] if i > 0 and not is_id_segment(segments[i - 1]) else None
            base = f"{singular(_snake(prev))}_id" if prev else f"param{len(names) + 1}"
            name, n = base, 2
            while name in names:
                name, n = f"{base}{n}", n + 1
            names.append(name)
            values.append(seg)
            out.append("{" + name + "}")
        else:
            out.append(seg)
    return "/" + "/".join(out), names, values


# ---------------------------------------------------------------- naming


def operation_name(method: str, template: str) -> str:
    segments = [s for s in template.split("/") if s]
    while segments and (segments[0].lower() in PREFIX_SEGMENTS or VERSION.match(segments[0])):
        segments = segments[1:]
    if not segments:
        return method.lower() + "_root"

    def is_param(s: str) -> bool:
        return s.startswith("{")

    last = segments[-1]
    literals = [_snake(s) for s in segments if not is_param(s)]

    if is_param(last):
        resource = singular(literals[-1]) if literals else "item"
        verb = {"GET": "get", "PUT": "update", "PATCH": "update", "DELETE": "delete", "POST": "create"}.get(
            method, method.lower()
        )
        parent = [singular(x) for x in literals[:-1]]
        return "_".join([verb, *parent[-1:], resource]) if parent and parent[-1] != resource else f"{verb}_{resource}"

    last_snake = _snake(last)
    parent_is_param = len(segments) >= 2 and is_param(segments[-2])
    parent_resource = singular(literals[-2]) if len(literals) >= 2 else None
    plural = last_snake.endswith("s") and not last_snake.endswith("ss")

    if parent_is_param and parent_resource:
        if method == "GET":
            return f"list_{parent_resource}_{last_snake}" if plural else f"get_{parent_resource}_{last_snake}"
        if plural and method == "POST":
            return f"create_{parent_resource}_{singular(last_snake)}"
        return f"{last_snake}_{parent_resource}"  # an action: bind_quote, cancel_policy

    if method == "GET":
        return f"list_{last_snake}" if plural else f"get_{last_snake}"
    if method == "POST" and plural:
        return f"create_{singular(last_snake)}"
    if method in {"PUT", "PATCH"}:
        return f"update_{last_snake}"
    if method == "DELETE":
        return f"delete_{last_snake}"
    return last_snake


def classify_risk(method: str, name: str) -> str:
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    if method == "DELETE" or IRREVERSIBLE.search(name):
        return "irreversible"
    return "write"


# ---------------------------------------------------------------- auth


def _string_leaves(value: Any, prefix: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _string_leaves(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(value, str):
        yield prefix, value


def detect_auth(exchanges: list[Exchange]) -> tuple[AuthSpec | None, Exchange | None]:
    """Find a response that hands out a token which later requests send back."""
    for i, ex in enumerate(exchanges):
        if ex.method != "POST" or not isinstance(ex.response_json, dict):
            continue
        candidates = [(p, v) for p, v in _string_leaves(ex.response_json) if len(v) >= 16]
        for later in exchanges[i + 1 :]:
            for header, value in later.request_headers.items():
                for json_path, token in candidates:
                    if token and token in value:
                        scheme = value.split(token)[0].strip()
                        fields = sorted(ex.request_json) if isinstance(ex.request_json, dict) else []
                        spec = AuthSpec(
                            login_method=ex.method,
                            login_path=templatize(ex.path)[0],
                            credential_fields=fields,
                            token_json_path=json_path,
                            header=header,
                            scheme=scheme,
                        )
                        return spec, ex
    return None, None


# ---------------------------------------------------------------- schemas


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if SENSITIVE_KEY.search(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def build_operation(
    method: str, template: str, path_params: list[str], samples: list[tuple[Exchange, list[str]]]
) -> Operation:
    name = operation_name(method, template)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for idx, param in enumerate(path_params):
        examples = sorted({values[idx] for _, values in samples})[:3]
        properties[param] = {"type": "string", "description": f"Path parameter, e.g. {', '.join(examples)}"}
        required.append(param)

    query_values: dict[str, list[str]] = defaultdict(list)
    query_presence: Counter[str] = Counter()
    for ex, _ in samples:
        for key, vals in ex.query.items():
            query_values[key].extend(vals)
            query_presence[key] += 1
    for key in sorted(query_values):
        schema = infer_scalar_from_strings(query_values[key])
        schema["description"] = f"Query parameter, e.g. {query_values[key][0]}"
        properties[key] = schema
        if query_presence[key] == len(samples):
            required.append(key)

    bodies = [ex.request_json for ex, _ in samples if ex.request_json is not None]
    if bodies:
        body_schema = infer_many(bodies)
        body_schema["description"] = "JSON request body"
        properties["body"] = body_schema
        if len(bodies) == len(samples):
            required.append("body")

    output_schema = infer_many([ex.response_json for ex, _ in samples if ex.response_json is not None])
    risk = classify_risk(method, name)

    first, first_values = samples[0]
    example = {
        **dict(zip(path_params, first_values)),
        **{k: v[0] for k, v in first.query.items()},
    }
    if first.request_json is not None:
        example["body"] = redact(first.request_json)

    action = name.replace("_", " ")
    description = f"{action[0].upper()}{action[1:]}. Returns {summarize(output_schema)}."
    if risk != "read":
        description += f" SIDE EFFECT ({risk}): changes data in the app."

    return Operation(
        name=name,
        method=method,
        path_template=template,
        description=description,
        path_params=path_params,
        query_params=sorted(query_values),
        has_body=bool(bodies),
        input_schema={"type": "object", "properties": properties, "required": required},
        output_schema=output_schema,
        risk=risk,  # type: ignore[arg-type]
        observed=len(samples),
        example_request=example,
    )


# ---------------------------------------------------------------- entry point


def compile_exchanges(
    exchanges: list[Exchange], app: str, base_url: str | None = None, sources: list[str] | None = None
) -> Catalog:
    api, dropped = filter_api(exchanges)
    if base_url is None:
        origins = Counter(ex.origin for ex in api)
        base_url = origins.most_common(1)[0][0] if origins else ""
    api = [ex for ex in api if ex.origin == base_url.rstrip("/")] or api

    auth, login_exchange = detect_auth(api)
    login_key = (login_exchange.method, templatize(login_exchange.path)[0]) if login_exchange else None

    groups: dict[tuple[str, str], list[tuple[Exchange, list[str]]]] = defaultdict(list)
    params_for: dict[tuple[str, str], list[str]] = {}
    for ex in api:
        template, names, values = templatize(ex.path)
        key = (ex.method, template)
        if key == login_key:
            continue
        groups[key].append((ex, values))
        params_for[key] = names

    operations = [build_operation(m, t, params_for[(m, t)], samples) for (m, t), samples in groups.items()]

    seen: Counter[str] = Counter()
    for op in operations:
        seen[op.name] += 1
        if seen[op.name] > 1:
            op.name = f"{op.name}_{op.method.lower()}{seen[op.name]}"

    operations.sort(key=lambda o: (o.path_template, o.method))
    reasons = Counter(reason for _, reason in dropped)
    return Catalog(
        app=app,
        base_url=base_url,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        sources=sources or [],
        auth=auth,
        operations=operations,
        dropped=dict(reasons),
    )


def compile_har(paths: str | Path | list[str | Path], app: str, base_url: str | None = None) -> Catalog:
    """Compile one or more HAR files (e.g. several sessions against the same app)."""
    if isinstance(paths, (str, Path)):
        paths = [paths]
    exchanges: list[Exchange] = []
    for p in paths:
        exchanges.extend(load_exchanges(p))
    return compile_exchanges(exchanges, app=app, base_url=base_url, sources=[Path(p).name for p in paths])
