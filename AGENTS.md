# AGENTS.md

## Project
Vietnamese Stock Realtime Signal Telegram Bot.

## Working principle
Build incrementally. Never implement the whole system in one pass.

## Mandatory reading order
Before coding:
1. `START_HERE.md`
2. `AGENTS.md`
3. `TASKS.md`
4. `PROJECT_CONTEXT.md`
5. relevant docs under `docs/`

## Hard rules

1. Work on ONE phase at a time.
2. Work on ONE small task group at a time.
3. Do not start later phases until the active phase passes its acceptance criteria.
4. Every meaningful change must be tested.
5. Never fabricate successful tests.
6. If a test cannot run, write `NOT TESTED` and explain why.
7. Update `PROJECT_CONTEXT.md` after each meaningful task.
8. Update `TASKS.md` checkboxes only when evidence exists.
9. Preserve existing working code unless change is necessary.
10. Separate:
   - data acquisition
   - decoding
   - normalization
   - market state
   - indicators
   - strategy
   - scanner
   - alerts
   - Telegram
   - backtest
11. Never hard-code secrets.
12. Never commit `.env`.
13. Do not request or store Vietcap username/password/access-token/refresh-token.
14. Do not place real brokerage orders.
15. Do not implement Trading API in V1.
16. Treat Vietcap frontend interfaces as unofficial/internal and subject to change.
17. Never guess undocumented protobuf fields if the schema does not support them.
18. Runtime evidence overrides assumptions in documentation.
19. Keep confirmed facts separate from assumptions.
20. Backtest and live signal logic must eventually use the same strategy implementation.
21. No look-ahead bias in indicators/backtests.
22. Automatic Telegram alerts must eventually be deduplicated.
23. Add logging and error handling for all network code.
24. Prefer mature libraries over handwritten protocol stacks.
25. For Socket.IO use `python-socketio` first; do not hand-write Engine.IO unless necessary.

## Mandatory response after each coding iteration

Report:

### Completed
What was implemented.

### Files changed
Exact paths.

### Tests
Commands + PASS/FAIL.

### Findings
New technical facts.

### Problems
Known unresolved issues.

### Documentation
Confirm updates to:
- `PROJECT_CONTEXT.md`
- `TASKS.md`

### Next
Only the next small task, not the whole roadmap.

## Stop condition
When the current task acceptance criteria are met:
- update docs,
- report results,
- STOP.
Do not automatically continue into the next phase.
