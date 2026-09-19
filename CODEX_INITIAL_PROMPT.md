# INITIAL PROMPT FOR CODEX

Read these files first, in this exact order:

1. `START_HERE.md`
2. `AGENTS.md`
3. `TASKS.md`
4. `PROJECT_CONTEXT.md`
5. `docs/VIETCAP_PROTOCOL.md`
6. `docs/ARCHITECTURE.md`

Then inspect the repository.

IMPORTANT:
- Work ONLY on the ACTIVE PHASE in `TASKS.md`.
- The active phase is Phase 0.
- Do not code the whole bot.
- Do not implement Telegram, indicators, scanner, strategy, backtest, or news now.
- Do not start Phase 1 unless the user explicitly asks you to continue after Phase 0.

For Phase 0:

1. Inspect repository structure.
2. Inspect Python version/dependencies.
3. Identify whether existing code can be preserved.
4. Create only the minimum missing folders/files required for the future Vietcap provider.
5. Check `.env.example` and `.gitignore`.
6. Update `PROJECT_CONTEXT.md` with:
   - real repo structure,
   - current dependencies,
   - confirmed integration point,
   - assumptions,
   - next small task.
7. Update `TASKS.md` checkboxes only for items actually completed.
8. Do not fabricate tests.
9. Report:
   - Completed
   - Files changed
   - Tests
   - Findings
   - Problems
   - Documentation updates
   - Next
10. STOP.

Do not continue automatically to Phase 1.
