# Architecture

```
            ┌──────────┐   HAR    ┌────────────┐  catalog.json  ┌───────────┐
 browser ──▶│ recorder │ ───────▶ │  compiler  │ ─────────────▶ │  runtime  │──▶ live app
 (you)      └──────────┘          └────────────┘                └───────────┘
                                        ▲                          ▲      ▲
                                        │                          │      │
                              ┌─────────┴─────────┐        ┌──────┴──┐ ┌─┴───┐
                              │ evals + fixtures  │        │   MCP   │ │ CLI │
                              │   (scoreboard)    │        │ server  │ │call │
                              └───────────────────┘        └─────────┘ └─────┘
```

## Stages

**1. Record** (`recorder.py`). Playwright opens a real browser with HAR recording on, content
embedded. The user drives. Output is a standard HAR 1.2 file. Scripted sessions in
`testing/sessions.py` produce the same format in-process for fixtures.

**2. Filter** (`har.py: is_api_call`). Keep JSON request/response pairs with status < 400. Drop
static assets, HTML, and instrumentation paths (telemetry, analytics, beacons...).

**3. Templatize** (`compiler.py: templatize`). Replace id-like path segments (digits, UUIDs, hex,
`POL-100234`-style slugs) with named params (`/policies/{policy_id}`). Param name comes from
the preceding resource segment.

**4. Group.** One operation per (method, path template). *Known gap:* RPC/GraphQL endpoints
need a body discriminator too; see roadmap.

**5. Infer schemas** (`schema.py`). Merge JSON Schemas across all samples. A field is required
only if every sample had it; types widen (int+float -> number); string formats (date,
date-time, uuid, email) are kept when consistent. Query params recover ints/bools.

**6. Detect auth** (`compiler.py: detect_auth`). Find a response containing a long string that
later requests send back in a header (Bearer token, CSRF token). That request becomes the login
flow; its body keys become credential fields. Login is not exposed as a tool.

**7. Name and classify.** Heuristic REST naming (`list_policies`, `bind_quote`); optional LLM
refinement (`naming.py`). Risk: GET = read, other methods = write, verbs like
bind/delete/cancel/submit/pay = irreversible.

**8. Execute** (`runtime.py`). Validate args against the schema's required/known fields, build the
request, log in on first use and once more on a 401, dry-run any write without `confirm`,
append every call to a JSONL audit log.

**9. Serve** (`mcp_server.py`). One MCP tool per operation, with `readOnlyHint` /
`destructiveHint` annotations and a `confirm` arg on writes.

## The catalog is the contract

`catalog.json` is plain JSON, diffable, versionable. When an app changes, recompile and diff the
catalog: a renamed field or vanished endpoint shows up in review. This is the basis for drift
detection.

## Design constraints

- The compile + eval loop is offline and LLM-free so iteration costs nothing.
- The runtime never calls an LLM.
- Credentials come from the environment (`PORTOLAN_<FIELD>`), never from the catalog.
- Everything an agent can do is visible in the catalog and the audit log.
