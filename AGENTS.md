# A-Share V4 Project Instructions

This repository is the standalone A-share overnight research and paper-trading
project.  Every coding session must begin by reading, in order:

1. `PROJECT.md`
2. `docs/project-state.json`
3. `docs/ROADMAP.md`
4. The relevant module contract in `docs/MODULES.md`

## Non-negotiable invariants

- The production gate remains `research_locked` until strict 14:50/next-session
  09:30 evidence, walk-forward, stress and model-publication gates all pass.
- Never use future data, lower a strict evidence threshold to manufacture a
  result, claim profitability, or equate a rule score with win probability.
- Runtime code must not import `v3.*`; the V3 working tree is retired and may
  exist only in the local verified retirement backup.
- The two required notifications are 09:25 observation and 14:50 confirmation.
- Confirmation candidates must be a subset of the same-day 09:25 mother pool.
- Paper trading is local only: 14:50 confirmation buy, next open session after
  09:30 sell, CNY 100,000 initial capital, at most one-third per symbol.
- Strict evidence, paper-account evidence and proxy backtests are separate
  cohorts and must never be merged.
- P3/P4/P5 were explicitly cut over on 2026-08-09: P3 is the only local paper
  account writer, P4 is the only active business scheduler/notification owner,
  and P5 is the read-only dashboard on port 8898. They remain `in_progress`
  until real-window acceptance passes. Any P1/P2 live failure takes immediate
  repair priority; never enable a second writer or legacy scheduler.
- P6/P7/P8 may proceed only for deterministic offline contracts and isolated
  tests. Do not fabricate strict samples, publish a model, change
  `research_locked`, archive historical code, restore over live data, or alter
  production entrypoints without their data gates and separate authorization.
- Preserve user-owned untracked files and unrelated worktree changes.
- Cutover preparation tools are report-only. Never reinterpret a nonzero
  cutover-preflight exit as permission to register tasks, migrate an account,
  switch port 8898, send PushPlus, or enable a production writer.

## Development workflow

- Work in the phase marked `active_phase` in `docs/project-state.json` unless
  the user explicitly changes priority.
- Before implementation, state the module contract and acceptance criteria.
- Add or update tests for every contract change.
- Update `docs/project-state.json`, `docs/CHANGELOG.md` and affected documents
  in the same change.
- A phase is complete only when its exit criteria in `docs/ROADMAP.md` pass.
- Run `python scripts/project_status.py` and the relevant pytest suite before
  handoff.  The status command must not mutate trading or external state.

## Runtime entrypoints

- Dashboard: `python -m v4.p5_dashboard --port 8898 --data-dir v4/data` at `http://127.0.0.1:8898/`
- Decisions: `python v4/scripts/decision_job.py morning|confirmation`
- Morning: `python v4/scripts/morning_push.py`
- Confirmation: `python v4/scripts/afternoon_push.py`
- Paper execution: authorized P4 adapter calls `v4.p3_production`; `paper_trade.py` is compatibility-only

The Windows task names are deployment details, not ownership boundaries.
