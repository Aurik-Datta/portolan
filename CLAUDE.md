@AGENTS.md

## Claude Code specifics

- Project subagents live in `.claude/agents/`:
  - `fixture-builder`: adds a new fixture app + scripted session + eval spec reproducing a pattern the compiler can't handle yet.
  - `eval-runner`: runs tests and the scoreboard, compares against the last committed result, reports regressions.
- Before finishing any compiler change: run `make check` (lint, tests, baseline regression gate) and paste the
  scoreboard into your summary. A Stop hook (`.claude/hooks/check-on-stop.sh`) runs it automatically when
  `portolan/`, `tests/`, `evals/` or the Makefile changed, and sends failures back to you.
- `.claude/settings.json` pre-approves the test/eval/git/PR commands for unattended work. Nothing is denied, so
  `make check` (and CI) are the guardrail: don't push anything that fails it.
- Update the "Current state" section of AGENTS.md when the scoreboard or next task changes.
