"""portolan: record a web app, compile it into typed operations, serve them to agents.

    portolan demo                                   # end-to-end on the built-in fixture, no setup
    portolan record https://app.example.com -o recordings/app.har
    portolan compile recordings/app.har --app myapp -o catalogs/myapp.json
    portolan inspect catalogs/myapp.json
    portolan call catalogs/myapp.json list_policies --args '{"status": "active"}'
    portolan serve catalogs/myapp.json              # MCP over stdio
    portolan eval                                   # scoreboard over evals/*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from portolan.catalog import Catalog


def cmd_record(a: argparse.Namespace) -> int:
    from portolan.recorder import record

    record(a.url, a.out, storage_state=a.storage_state, url_filter=a.filter)
    return 0


def cmd_compile(a: argparse.Namespace) -> int:
    from portolan.compiler import compile_har

    catalog = compile_har(a.har, app=a.app, base_url=a.base_url)
    if a.llm:
        from portolan.naming import refine_with_llm

        catalog = refine_with_llm(catalog)
    out = catalog.save(a.out or f"catalogs/{a.app}.json")
    print(f"{len(catalog.operations)} operations -> {out}")
    print(_table(catalog))
    return 0


def _table(catalog: Catalog) -> str:
    rows = [(op.name, op.method, op.path_template, op.risk, str(op.observed)) for op in catalog.operations]
    header = ("operation", "method", "path", "risk", "seen")
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(header)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(header, widths))]
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows]
    auth = catalog.auth
    lines.append(
        f"auth: {auth.scheme} token from {auth.login_method} {auth.login_path} ({', '.join(auth.credential_fields)})"
        if auth else "auth: none detected"
    )
    if catalog.dropped:
        lines.append("dropped: " + ", ".join(f"{k} x{v}" for k, v in catalog.dropped.items()))
    return "\n".join(lines)


def cmd_inspect(a: argparse.Namespace) -> int:
    catalog = Catalog.load(a.catalog)
    if a.operation:
        print(json.dumps(catalog.get(a.operation).model_dump(mode="json"), indent=2))
    else:
        print(_table(catalog))
    return 0


def cmd_call(a: argparse.Namespace) -> int:
    from portolan.runtime import Executor

    catalog = Catalog.load(a.catalog)
    if a.base_url:
        catalog.base_url = a.base_url
    executor = Executor(catalog, audit_log=a.audit_log)
    result = executor.call(a.operation, json.loads(a.args), confirm=a.confirm)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("dry_run") or result.get("ok") else 1


def cmd_serve(a: argparse.Namespace) -> int:
    from portolan.mcp_server import serve_stdio
    from portolan.runtime import Executor

    catalog = Catalog.load(a.catalog)
    if a.base_url:
        catalog.base_url = a.base_url
    serve_stdio(catalog, Executor(catalog, audit_log=a.audit_log))
    return 0


def cmd_eval(a: argparse.Namespace) -> int:
    from portolan.evals import format_table, run_eval

    specs = a.specs or sorted(p for p in Path("evals").glob("*.json") if p.name != "baseline.json")
    results = [run_eval(s, workdir=a.workdir) for s in specs]
    print(format_table(results))
    if a.write_baseline:
        keep = ("recall", "precision", "risk", "auth", "scenarios", "score")
        baseline = {r.app: {k: v for k, v in r.to_dict().items() if k in keep} for r in results}
        Path(a.write_baseline).write_text(json.dumps(baseline, indent=2) + "\n")
        print(f"baseline written to {a.write_baseline}")
    return 0 if all(r.score >= a.min_score for r in results) else 1


def cmd_demo(a: argparse.Namespace) -> int:
    from fastapi.testclient import TestClient

    from portolan.compiler import compile_har
    from portolan.runtime import Executor
    from portolan.testing.carrier_portal import create_app
    from portolan.testing.sessions import BASE_URL, record_carrier_portal_session

    out = Path(a.workdir)
    print("1. Recording a scripted session against the fake carrier portal...")
    writer = record_carrier_portal_session(out / "demo.har")
    print(f"   {len(writer.entries)} requests captured -> {out / 'demo.har'}")

    print("\n2. Compiling traffic into typed operations...")
    catalog = compile_har(out / "demo.har", app="acme-portal", base_url=BASE_URL)
    catalog.save(out / "demo.catalog.json")
    print(_table(catalog))

    print("\n3. Calling the compiled operations against a fresh portal (no browser)...")
    executor = Executor(
        catalog,
        client=TestClient(create_app(), base_url=BASE_URL),
        credentials={"username": "broker@example.com", "password": "hunter2"},
    )
    policies = executor.call("list_policies", {"status": "active"})
    print(f"   list_policies -> HTTP {policies['status']}, {policies['data']['total']} policies")
    preview = executor.call("create_quote", {"body": {
        "line": "auto",
        "insured": {"name": "Demo Driver", "province": "ON", "date_of_birth": "1993-06-01"},
        "vehicle": {"year": 2020, "make": "Subaru", "model": "Impreza"},
        "coverage": {"liability_limit": 1_000_000, "deductible": 1000},
    }})
    print(f"   create_quote (no confirm) -> dry run: {preview['dry_run']}")
    quote = executor.call("create_quote", {"body": preview["would_send"]["json"]}, confirm=True)
    data = quote["data"]
    print(f"   create_quote (confirm) -> premium ${data['annual_premium']}, quote {data['quote_id'][:8]}...")
    print(f"\nCatalog written to {out / 'demo.catalog.json'}. Try: portolan serve {out / 'demo.catalog.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="portolan", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("record", help="record a browser session to HAR (Playwright)")
    s.add_argument("url")
    s.add_argument("-o", "--out", default="recordings/session.har")
    s.add_argument("--storage-state", help="Playwright storage state JSON to start signed in")
    s.add_argument("--filter", help="only record URLs matching this glob/regex")
    s.set_defaults(fn=cmd_record)

    s = sub.add_parser("compile", help="compile HAR file(s) into an operation catalog")
    s.add_argument("har", nargs="+")
    s.add_argument("--app", required=True)
    s.add_argument("--base-url")
    s.add_argument("-o", "--out")
    s.add_argument("--llm", action="store_true", help="refine names/descriptions with an LLM (needs [llm] extra)")
    s.set_defaults(fn=cmd_compile)

    s = sub.add_parser("inspect", help="show a catalog, or one operation in full")
    s.add_argument("catalog")
    s.add_argument("operation", nargs="?")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("call", help="call one operation against the live app")
    s.add_argument("catalog")
    s.add_argument("operation")
    s.add_argument("--args", default="{}", help="JSON object of arguments")
    s.add_argument("--confirm", action="store_true", help="actually execute write operations")
    s.add_argument("--base-url")
    s.add_argument("--audit-log", default="portolan-audit.jsonl")
    s.set_defaults(fn=cmd_call)

    s = sub.add_parser("serve", help="serve a catalog as an MCP server over stdio")
    s.add_argument("catalog")
    s.add_argument("--base-url")
    s.add_argument("--audit-log", default="portolan-audit.jsonl")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("eval", help="run the eval scoreboard")
    s.add_argument("specs", nargs="*")
    s.add_argument("--workdir", default="evals/results")
    s.add_argument("--min-score", type=float, default=0.0)
    s.add_argument("--write-baseline", metavar="PATH", help="save scores as the accepted baseline")
    s.set_defaults(fn=cmd_eval)

    s = sub.add_parser("demo", help="record, compile and call the built-in fixture end to end")
    s.add_argument("--workdir", default="evals/results")
    s.set_defaults(fn=cmd_demo)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
