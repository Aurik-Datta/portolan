"""Optional LLM pass: better operation names and descriptions.

The heuristic names from `compiler.operation_name` are decent for REST-ish apps
and poor for RPC-style ones (POST /api/do?action=...). This pass asks a model
to rename and describe operations, using only schemas and redacted examples.

It runs at compile time only. Compiled tools never call a model at runtime.
Requires: pip install -e ".[llm]" and ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import json
import os
import re

from portolan.catalog import Catalog

DEFAULT_MODEL = os.environ.get("PORTOLAN_MODEL", "claude-haiku-5-5")

PROMPT = """You are naming API operations that were reverse-engineered from a web app's traffic.
For each operation, return a snake_case verb_noun name (max 4 words) and a one-sentence
description an AI agent would use to decide when to call it. Keep names unique.
Do not change what the operation does. Reply with JSON only:
{{"operations": [{{"key": "<METHOD path>", "name": "...", "description": "..."}}]}}

App: {app}
Operations:
{ops}"""


def refine_with_llm(catalog: Catalog, model: str = DEFAULT_MODEL) -> Catalog:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - optional extra
        raise SystemExit('LLM naming needs: pip install -e ".[llm]"') from exc

    ops = [
        {
            "key": op.key,
            "current_name": op.name,
            "risk": op.risk,
            "inputs": list(op.input_schema.get("properties", {})),
            "output_fields": list(op.output_schema.get("properties", {}))[:12],
        }
        for op in catalog.operations
    ]
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": PROMPT.format(app=catalog.app, ops=json.dumps(ops, indent=1))}],
    )
    text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return catalog
    proposals = {p["key"]: p for p in json.loads(match.group(0)).get("operations", [])}

    taken: set[str] = set()
    for op in catalog.operations:
        p = proposals.get(op.key)
        if not p:
            taken.add(op.name)
            continue
        name = re.sub(r"[^a-z0-9_]", "_", p.get("name", op.name).lower()).strip("_") or op.name
        if name in taken:
            name = op.name
        taken.add(name)
        op.name = name
        if p.get("description"):
            suffix = f" SIDE EFFECT ({op.risk}): changes data in the app." if op.side_effect else ""
            op.description = p["description"].rstrip() + suffix
    return catalog
