"""Expose a compiled catalog as an MCP server, so any agent can call the app.

Each operation becomes one tool. Write operations gain a `confirm` argument and
are dry-run by default; tool annotations tell MCP clients which tools are
read-only and which are destructive.
"""

from __future__ import annotations

import json
from typing import Any

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server

from portolan.catalog import Catalog, Operation
from portolan.runtime import Executor, OperationError


def tool_for(op: Operation) -> types.Tool:
    schema = json.loads(json.dumps(op.input_schema))
    if op.side_effect:
        schema.setdefault("properties", {})["confirm"] = {
            "type": "boolean",
            "default": False,
            "description": "Set true to actually execute. Without it you get a dry-run preview.",
        }
    return types.Tool(
        name=op.name,
        description=op.description,
        inputSchema=schema,
        outputSchema=None,
        annotations=types.ToolAnnotations(
            title=op.name.replace("_", " ").capitalize(),
            readOnlyHint=not op.side_effect,
            destructiveHint=op.risk == "irreversible",
            idempotentHint=op.method in {"GET", "PUT", "DELETE"},
            openWorldHint=True,
        ),
    )


def make_handlers(catalog: Catalog, executor: Executor):  # noqa: ANN201 - returns two async callables
    """The list/call handlers, separate from transport so tests can call them directly."""
    tools = [tool_for(op) for op in catalog.operations]

    async def list_tools(ctx: Any, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        args = dict(params.arguments or {})
        try:
            result = await anyio.to_thread.run_sync(lambda: executor.call(params.name, args))
        except (OperationError, KeyError) as exc:
            return types.CallToolResult(content=[types.TextContent(type="text", text=str(exc))], isError=True)
        is_error = not result.get("dry_run") and not result.get("ok", False)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))],
            structuredContent=result,
            isError=is_error,
        )

    return list_tools, call_tool


def build_server(catalog: Catalog, executor: Executor) -> Server:
    list_tools, call_tool = make_handlers(catalog, executor)
    return Server(
        f"portolan-{catalog.app}",
        instructions=(
            f"Typed operations for {catalog.app}, compiled by Portolan from recorded traffic. "
            "Tools marked with side effects return a dry-run preview unless called with confirm=true; "
            "show the preview to the user before confirming."
        ),
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def serve_stdio(catalog: Catalog, executor: Executor) -> None:
    from mcp.server.stdio import stdio_server

    server = build_server(catalog, executor)

    async def main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(main)
