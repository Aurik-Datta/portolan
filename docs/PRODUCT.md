# Product

## One line

Point Portolan at a web app with no API. Get back typed, tested tools any AI agent can call.

## The problem

Agents are only as useful as the systems they can act on. Most business software (carrier
portals, government sites, legacy ERPs, internal tools) has no public API. Today an agent has two
options, both bad:

- **Drive the UI with computer use / browser agents.** Flexible, but slow, expensive per step,
  and not reliable enough for high-volume or high-stakes work (frontier agents score ~85% on
  OSWorld-Verified as of Sept 2026; nobody wants 85% on "bind this policy").
- **Record-and-replay a demonstrated workflow** (OpenAI Codex Record & Replay, Microsoft Skill
  Recorder, SkillForge). Captures one path a human walked, as clicks, with no guarantees.

Underneath almost every modern web UI is an internal JSON API the front end calls. Calling it
directly is faster, cheaper and deterministic. CMU's "Beyond Browsing" (ACL Findings 2025) found
API-plus-browsing agents beat browsing-only agents by 24+ points on WebArena at a fraction of
the cost. Portolan finds that API and turns it into a contract.

## Who it's for (first)

**Developers building agents that must act on someone else's web app.** Typical examples: an
insurtech automating carrier portals, an ops team wiring an agent into a vendor dashboard, a
founder integrating with a partner that "doesn't have an API yet."

They currently write and babysit Playwright scripts or hand-reverse-engineer endpoints in
DevTools. Portolan replaces that with: record -> compile -> serve -> test.

## Why a dev tool first (decision, Oct 2026)

We considered (a) a horizontal "make every app agent-ready" platform and (b) a vertical managed
API for insurance carrier portals. We're starting with a **self-serve developer tool** because:

- It's testable by us, alone, this month: fixtures + scoreboard, no sales cycle.
- Developers judge it on quality, which is where our edge has to come from anyway.
- It keeps the vertical option open: a managed carrier-portal API is the same engine plus
  maintenance, normalization and relationships. Design partners from the dev tool tell us which
  vertical to pick.

What the dev tool does **not** solve on its own (from the stress test): no network-effect moat,
and broad competition. Our answer is to be the best at *verified* operations: typed contracts,
dry-run safety, audit logs, regression tests, drift detection. Not "autonomous" for its own sake.

## Differentiation

| | UI agents (Skyvern, Browser Use, computer use) | Record & replay (Codex, Skill Recorder) | Integuru (closest) | **Portolan** |
|---|---|---|---|---|
| Executes via | screen / DOM | replayed clicks / LLM | reverse-engineered API calls | reverse-engineered API calls, DOM fallback later |
| Output | an agent run | a SKILL.md | integration code | a typed catalog + MCP server |
| Safety on writes | prompt-level | prompt-level | caller's problem | dry-run by default, risk levels, audit log |
| Verifiable | benchmark scores | no | per-integration | scoreboard + per-operation tests, drift detection (planned) |

Closest competitor: **Integuru** (YC W24) builds integrations from internal APIs (HAR -> code,
AGPL agent). Study it; beat it on contracts, safety, testing and developer experience.

## Principles

1. Determinism beats autonomy. A tool that works every time beats one that's clever sometimes.
2. Writes are dangerous. Dry-run by default, explicit confirm, full audit.
3. The user is authorized; we act as them. Use their credentials and their access. No CAPTCHA
   solving, no bypassing access controls, no scraping data they couldn't see themselves.
4. No customer data at rest unless they ask. Redact examples, gitignore recordings.

## Risks we're tracking

1. **Commoditization** by general agents and lab tools. Mitigation: compete on guarantees.
2. **Legal / ToS.** Calling internal APIs from a server looks less like "the user browsing" than
   UI agents do (see Amazon v. Perplexity, 9th Cir. Aug 2026, which turned on user-side design).
   Mitigation: run under the user's own session, identify the client, get counsel before any
   hosted offering. Not legal advice; revisit before launch.
3. **Apps shipping their own MCP/WebMCP.** Shrinks the modern-SaaS market; legacy portals will lag
   for years. That long tail is our market.
4. **Write-operation liability.** Mitigation: the safety model above, plus approval flows.

## What success looks like (next 90 days)

- Scoreboard: 5+ fixture patterns (REST, RPC, GraphQL, cookie+CSRF, pagination) all >= 0.9.
- 3 real apps compiled end to end by people other than us.
- 10 developers using it weekly; 2 asking to pay for hosted drift detection or a managed connector.
