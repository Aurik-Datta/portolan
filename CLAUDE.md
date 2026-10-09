@AGENTS.md

## Claude Code specifics

- Project subagents live in `.claude/agents/`:
  - `fixture-builder`: adds a new fixture app + scripted session + eval spec reproducing a pattern the compiler can't handle yet.
  - `eval-runner`: runs tests and the scoreboard, compares against the last committed result, reports regressions.
- Before finishing any compiler change: run `make test` and `make eval`, and paste the scoreboard into your summary.
- Update the "Current state" section of AGENTS.md when the scoreboard or next task changes.
