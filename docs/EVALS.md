# Evals

The scoreboard is how we know a change helped. Run it with `make eval`.

## How it works

Each `evals/<app>.json` spec names:

- `fixture`: a FastAPI app factory (`module:create_app`), the fake target
- `session`: a function that records a HAR against it (stands in for a human with a recorder)
- `expect.operations`: what a correct compiler finds, by key (`METHOD /path/{*}`), with risk
- `expect.must_not_include`: paths that must not become tools (login, telemetry, HTML)
- `scenarios`: steps that call compiled operations against a **fresh** fixture instance

Scenario steps reference operations by key, not name, so renaming never breaks evals. Values can
reference earlier results: `"{{steps.0.data.quote_id}}"`. `{"action": "expire_sessions"}` calls
the fixture's `app.state.expire_sessions()` to test re-login.

## Metrics

| Metric | Meaning |
|---|---|
| recall | expected operations discovered |
| precision | discovered operations that were expected (noise lowers it) |
| risk | discovered operations with the right read / write / irreversible label |
| auth | login flow detected (or correctly absent) |
| scenarios | end-to-end steps that behaved as expected |
| score | mean of the five |

`make baseline` saves current scores to `evals/baseline.json`. `make check` (and CI) fails if any
metric for an app in the baseline drops below it; apps not yet in the baseline are not gated. The `eval-runner` agent compares
against it and flags regressions.

## Fixtures

| App | Pattern | Baseline | Notes |
|---|---|---|---|
| `carrier_portal` | REST, bearer token, UUID + slug ids, irreversible bind, noise-like resource names (`/events`) vs real noise (`/api/logs`) | 1.00 | the happy path |
| `legacy_erp` | RPC (`POST /rpc {method}`), cookie session + CSRF header, error envelopes | 0.20 | needs body discriminators |

## Patterns we still need fixtures for

- GraphQL (single endpoint, operationName as discriminator)
- Cursor and offset pagination
- Form-encoded posts and multipart file uploads
- Server-rendered apps where "API" responses are HTML fragments (htmx, Rails Turbo)
- Multi-step wizards with server-side state between steps
- Anti-replay tokens that rotate per request
- OAuth / SSO redirects in the login flow

Add one with the `fixture-builder` agent. A new fixture scoring low is a success: it's a
measured, reproducible problem.

## Honesty rules

- A fixture must be realistic for its pattern. Don't simplify it until the compiler passes.
- Never special-case fixture names, paths or values in the compiler.
- Real-app results (not fixtures) go in `docs/FIELD_NOTES.md` with what broke.
