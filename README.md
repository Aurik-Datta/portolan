# Portolan

**Compile any web app's hidden API into typed, tested tools for AI agents.**

Most business software has no public API, but its front end talks to an internal one. Portolan
watches you use the app, finds those calls, and compiles them into an operation catalog with
names, JSON schemas, auth handling and risk levels. Then it serves the catalog as an MCP server,
so an agent calls `create_quote(...)` instead of clicking at pixels.

```
portolan record https://portal.example.com -o recordings/portal.har   # you click around
portolan compile recordings/portal.har --app portal                    # -> catalogs/portal.json
portolan serve catalogs/portal.json                                    # MCP server for any agent
```

Status: early. Works end to end on REST-style apps; RPC/GraphQL support is next. See the
[roadmap](docs/ROADMAP.md).

## Try it in 30 seconds (no browser, no network)

```bash
pip install -e ".[dev]"
make demo
```

This records a scripted session against a fake insurance carrier portal, compiles it, and calls
the compiled operations:

```
operation              method  path                                 risk          seen
get_me                 GET     /api/me                              read          1
list_policies          GET     /api/policies                        read          2
get_policy             GET     /api/policies/{policy_id}            read          2
list_policy_documents  GET     /api/policies/{policy_id}/documents  read          2
create_quote           POST    /api/quotes                          write         2
get_quote              GET     /api/quotes/{quote_id}               read          2
bind_quote             POST    /api/quotes/{quote_id}/bind          irreversible  1
auth: Bearer token from POST /api/auth/login (password, username)
dropped: non-JSON response (text/html) x2, static asset x1, instrumentation x4
```

## Safety model

- **Writes are dry-run by default.** Any operation that changes data returns a preview of the
  exact request unless called with `confirm=true`.
- **Risk levels** (`read`, `write`, `irreversible`) are exposed to agents as MCP tool annotations.
- **Every call is audited** to a JSONL log, dry runs included.
- **Credentials stay out of the catalog.** The runtime logs in with `PORTOLAN_<FIELD>` env vars and
  re-authenticates when a session expires.
- **Only act as the user.** Portolan uses the user's own session and access. It does not solve
  CAPTCHAs or bypass access controls.

## Using it on a real app

```bash
pip install -e ".[record]" && playwright install chromium
portolan record https://app.you-have-access-to.com -o recordings/app.har
portolan compile recordings/app.har --app myapp
portolan inspect catalogs/myapp.json
PORTOLAN_USERNAME=... PORTOLAN_PASSWORD=... \
  portolan call catalogs/myapp.json list_things --args '{"status": "active"}'
```

Connect it to an MCP client (Claude Desktop, Claude Code, Cursor...):

```json
{
  "mcpServers": {
    "myapp": {
      "command": "portolan",
      "args": ["serve", "/abs/path/catalogs/myapp.json"],
      "env": {"PORTOLAN_USERNAME": "...", "PORTOLAN_PASSWORD": "..."}
    }
  }
}
```

Only record apps you're authorized to use, and check their terms. Recordings contain session
tokens and real data; `recordings/` is gitignored for that reason.

## Developing

```bash
make test       # unit tests, ~2s, offline
make eval       # scoreboard across fixture apps
make baseline   # accept current scores
make portal     # run the fake carrier portal on :8765 to try the recorder
```

Current scoreboard:

```
app             recall  precision  risk  auth  scenarios  score
carrier_portal  1.00    1.00       1.00  1.00  1.00       1.00
legacy_erp      0.00    0.00       0.00  1.00  0.00       0.20
```

`legacy_erp` is an RPC-style app (everything is `POST /rpc`) and is meant to fail until the
compiler learns body discriminators. That's the next task.

Docs: [product](docs/PRODUCT.md) · [architecture](docs/ARCHITECTURE.md) ·
[evals](docs/EVALS.md) · [roadmap](docs/ROADMAP.md) · [decisions](docs/DECISIONS.md).
Agents working in this repo: start with [AGENTS.md](AGENTS.md).
