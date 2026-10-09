# Roadmap

Ordered. Each milestone has an exit criterion we can measure.

## M0: Skeleton (done, Oct 2026)

Record -> compile -> call/serve works on a REST fixture. Scoreboard, 2 fixtures, safety model,
MCP server, CI-ready tests.

## M1: Patterns (weeks 1-3)

Goal: the compiler handles the API shapes real legacy apps use.

1. **RPC discriminators.** Split a shared endpoint into operations by constant body fields that
   vary across samples (`method`, `action`, `op`, `operationName`). Classify risk from the verb
   in the discriminator. Exit: `legacy_erp` >= 0.9, `carrier_portal` stays 1.00.
2. **App-level error envelopes.** Many apps return 200 with `{"error": {...}}`. Detect the
   envelope from samples and surface it as `ok: false`.
3. **GraphQL fixture + support** (operationName as discriminator, variables as inputs).
4. **Pagination fixture + support** (detect cursor/offset params; optional auto-paginate).
5. **Variance-based templating**, for ids that don't look like ids (`/orgs/acme/users`).

## M2: Real apps (weeks 3-5)

Goal: it works on apps we didn't write.

1. Record 5 real apps we have legitimate accounts on (start with open-source self-hostable ones:
   Odoo, ERPNext, Invoice Ninja, plus WebArena's GitLab/Magento clones) and log results in
   `docs/FIELD_NOTES.md`.
2. Multi-HAR compile (several sessions -> one catalog) and incremental recompile.
3. Recorder polish: storage-state login reuse, URL filtering, "record more" mode.
4. Exit: 3 real apps where a fresh agent completes a defined task through Portolan tools only.

## M3: Verification (weeks 5-8): the part people pay for

1. **Generated per-operation tests**: replay recorded reads, assert response schema still holds.
2. **Drift detection**: `portolan check` re-runs reads and diffs schemas; non-zero exit on breaking change.
3. **Catalog diff** in human-readable form for code review.
4. Approval hooks for irreversible ops (webhook / CLI prompt) beyond `confirm`.
5. Exit: break a fixture's API deliberately, and `portolan check` catches it with a clear message.

## M4: Distribution (weeks 8-12)

1. Package on PyPI, `uvx portolan`, a 3-minute demo video.
2. Hosted option experiment: managed `check` on a schedule with alerts. First thing to charge for.
3. Talk to 15 developers automating portals (insurtech, logistics, health admin). Decide whether
   to open a vertical design-partner track.

## Later / maybe

- DOM-automation fallback for actions with no clean API call.
- Autonomous exploration (agent drives the recorder to cover unvisited screens), *after* the
  compiler is strong on recorded traffic.
- TypeScript SDK output alongside MCP.
- Desktop apps.

## Founders' checklist

- [ ] Check employment IP-assignment and moonlighting clauses before significant work.
- [ ] Legal opinion on hosted execution before any hosted product (Canada + US).
- [ ] Decide license (MIT vs Apache-2.0 vs source-available) before first public release.
