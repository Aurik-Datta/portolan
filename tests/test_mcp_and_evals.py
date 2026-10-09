import json
from pathlib import Path

import anyio
import mcp.types as types

from portolan.evals import run_eval
from portolan.mcp_server import make_handlers

EVALS = Path(__file__).parent.parent / "evals"


def test_mcp_tools_mark_side_effects(portal_catalog, executor):
    list_tools, _ = make_handlers(portal_catalog, executor)
    # Compare wire format (camelCase), which is stable across MCP SDK versions.
    tools = {t.name: t.model_dump(by_alias=True) for t in anyio.run(list_tools, None, None).tools}

    assert tools["list_policies"]["annotations"]["readOnlyHint"] is True
    assert "confirm" not in tools["list_policies"]["inputSchema"]["properties"]

    bind = tools["bind_quote"]
    assert bind["annotations"]["destructiveHint"] is True
    assert "confirm" in bind["inputSchema"]["properties"]


def test_mcp_call_returns_dry_run_then_executes(portal_catalog, executor):
    _, call_tool = make_handlers(portal_catalog, executor)
    body = {
        "line": "auto",
        "insured": {"name": "M Cp", "province": "ON", "date_of_birth": "1990-01-01"},
        "vehicle": {"year": 2019, "make": "Ford", "model": "Focus"},
        "coverage": {"liability_limit": 1_000_000, "deductible": 500},
    }

    async def call(args):
        return await call_tool(None, types.CallToolRequestParams(name="create_quote", arguments=args))

    preview = anyio.run(call, {"body": body})
    assert json.loads(preview.content[0].text)["dry_run"] is True
    done = anyio.run(call, {"body": body, "confirm": True}).model_dump(by_alias=True)
    assert not done["isError"] and done["structuredContent"]["data"]["status"] == "quoted"


def test_mcp_bad_arguments_are_tool_errors(portal_catalog, executor):
    _, call_tool = make_handlers(portal_catalog, executor)
    result = anyio.run(call_tool, None, types.CallToolRequestParams(name="get_policy", arguments={}))
    assert result.model_dump(by_alias=True)["isError"] and "missing" in result.content[0].text


def test_carrier_portal_eval_is_perfect(tmp_path):
    result = run_eval(EVALS / "carrier_portal.json", workdir=tmp_path)
    assert result.score == 1.0, result.to_dict()


def test_every_eval_spec_runs(tmp_path):
    """Specs may score low (that's the point), but they must never crash."""
    for spec in sorted(p for p in EVALS.glob("*.json") if p.name != "baseline.json"):
        result = run_eval(spec, workdir=tmp_path)
        assert 0.0 <= result.score <= 1.0
