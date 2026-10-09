# Decisions

Short log of choices and why. Newest first. Add an entry for anything a future contributor
might otherwise undo.

## 2026-10-09: Developer tool first, vertical later

Context: the stress test found a horizontal "every app" platform has no moat and heavy
competition, while a vertical (insurance carrier portals) has proven pain but long sales cycles.
Decision: build a self-serve dev tool on a general engine; use real users to choose a vertical.
Consequence: optimize for developer experience and verifiable quality, not breadth claims.

## 2026-10-09: Learn from recorded traffic before autonomous exploration

Context: autonomous exploration is novel but unvalidated, and exploring write flows on a live app
means really creating records. Decision: compile from recordings the user makes; add
agent-driven exploration later as a way to fill coverage gaps.

## 2026-10-09: Internal API first, UI automation as fallback

Context: API calls are faster, cheaper and deterministic (CMU "Beyond Browsing", ACL Findings 2025).
Decision: every operation targets the underlying HTTP call; DOM fallback is a later milestone.

## 2026-10-09: Writes are dry-run by default

Decision: any non-GET operation returns a preview unless called with `confirm=true`. Every call is
audited. This is a product feature, not a dev convenience; don't remove it to simplify a demo.

## 2026-10-09: Offline, LLM-free compile and eval loop

Decision: compiler and evals are deterministic and network-free, so iteration costs nothing and
results are reproducible. LLMs are an optional compile-time pass (`naming.py`), never runtime.

## 2026-10-09: Catalog keys and the discriminator field

Decision: an operation's identity is `METHOD path_template [discriminator]`. Evals match on keys,
not names, so names can change (e.g. LLM refinement) without breaking anything.

## 2026-10-09: Python + MCP

Python for the compiler/eval loop (fast iteration, Playwright, pydantic). Output is MCP so any
agent framework can use it. A TypeScript SDK can come later from the same catalog.

## 2026-10-09: Working name "Portolan"

Portolan charts were medieval maps drawn from sailors' observed routes: maps built from
traffic. Rename freely; the package name appears in pyproject, imports and docs.
