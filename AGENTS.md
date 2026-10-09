# AGENTS.md

Context for any AI agent (Claude Code, Codex, Cursor, etc.) working in this repo.
Read this first, then `docs/PRODUCT.md` and `docs/ROADMAP.md`.

## What we're building

**Portolan** turns a web app with no public API into typed, tested tools an AI agent can call.
You record yourself using the app; Portolan finds the internal API calls the front end makes,
compiles them into an operation catalog (names, JSON schemas, auth, risk levels), and serves
that catalog as an MCP server. Agents call `create_quote(...)` instead of clicking at pixels.

We are building it as a **developer tool first**: a CLI + library a developer can point at an app
and get a working MCP server in minutes. A managed, vertical offering (e.g. insurance carrier
portals) may come later on top of the same engine. See `docs/PRODUCT.md` for why.

## The loop that matters

```
record (HAR) -> compile (catalog.json) -> serve (MCP) / call (CLI)
                     ^
                     |
          evals/*.json scoreboard tells us if a change helped
```

**The scoreboard is the source of truth.** Every change to the compiler should be justified by
`make eval`. If you improve one app and regress another, the scoreboard will say so.

## Commands

```bash
pip install -e ".[dev]"     # first time
make test                   # pytest, must stay green, runs in ~2s, no network
make eval                   # scoreboard across evals/*.json (fixtures, in-process, free)
make demo                   # record -> compile -> call against the fake carrier portal
portolan --help             # full CLI
```

Nothing in the test or eval loop touches the network or an LLM. Keep it that way: it is what
makes iteration free. LLM use is confined to `portolan/naming.py` (optional, compile-time only).

## Layout

| Path | What it is |
|---|---|
| `portolan/har.py` | HAR read/write, filtering traffic down to API calls (drops static, HTML, telemetry) |
| `portolan/compiler.py` | HAR -> catalog: path templating, grouping, schema inference, auth detection, naming, risk |
| `portolan/schema.py` | JSON Schema inference and merging across samples |
| `portolan/catalog.py` | Pydantic models for the catalog (the contract) |
| `portolan/runtime.py` | Executes operations: auth/re-login, dry-run for writes, audit log |
| `portolan/mcp_server.py` | Catalog -> MCP tools (annotations, `confirm` arg on writes) |
| `portolan/recorder.py` | Playwright recorder for real apps (optional extra) |
| `portolan/naming.py` | Optional LLM pass for names/descriptions |
| `portolan/evals.py` | Scoreboard runner |
| `portolan/testing/` | Fixture apps + scripted sessions (deterministic test targets) |
| `evals/*.json` | Eval specs: expected operations + end-to-end scenarios per fixture |
| `docs/` | Product, architecture, roadmap, decisions |

## Rules

1. **Safety model is non-negotiable.** Writes are dry-run unless `confirm=true`. Every call is
   audited. Agents never see credentials. Don't weaken these to make a test pass.
2. **Never store real customer data in the repo.** Real HARs contain PII and session tokens.
   `recordings/` is gitignored. Fixtures must use fake data. Examples in catalogs go through `redact()`.
3. **Add a fixture before adding a heuristic.** If the compiler fails on a pattern (RPC, GraphQL,
   CSRF, pagination...), first add a fixture app + eval spec that reproduces it, watch it score low,
   then fix the compiler. See `docs/EVALS.md`.
4. **Deterministic first, LLM second.** Prefer rules we can test. Use the LLM where rules
   genuinely can't decide (naming, semantic grouping), and keep it out of the runtime.
5. **Catalogs are the contract.** Changes to `catalog.py` are API changes; update `portolan_version`
   and note them in `docs/DECISIONS.md`.
6. Keep `make test` under ~10s and network-free. Type hints everywhere; `ruff` clean.
7. Record significant design choices as a short entry in `docs/DECISIONS.md`.

## Current state (update this section when it changes)

- Scoreboard: `carrier_portal` 1.00 (REST + bearer auth); `legacy_erp` 0.20.
- **Next task:** RPC-style endpoints. `legacy_erp` collapses into one `POST /rpc` tool because the
  compiler only groups by method + path. Teach it to split on body discriminators
  (`{"method": "invoice.create"}`); `Operation.discriminator` and runtime support already exist.
  Then classify risk from the discriminator verb (`list`/`get` = read). Target: `legacy_erp` >= 0.9
  with `carrier_portal` still 1.00. Full list in `docs/ROADMAP.md`.
