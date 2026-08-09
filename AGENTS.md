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
- Runtime code in `v4/` must not import `v3.*`; V3 is historical only.
- The two required notifications are 09:25 observation and 14:50 confirmation.
- Confirmation candidates must be a subset of the same-day 09:25 mother pool.
- Paper trading is local only: 14:50 confirmation buy, next open session after
  09:30 sell, CNY 100,000 initial capital, at most one-third per symbol.
- Strict evidence, paper-account evidence and proxy backtests are separate
  cohorts and must never be merged.
- P3 may proceed in offline-only development while P1/P2 live-window evidence
  is pending. Do not enable P3 scheduling, connect it to the daily paper-fill
  production chain, or mark P3 complete. Any P1/P2 live-window failure pauses
  P3 immediately and takes repair priority.
- P4 may proceed only as isolated offline contract development. Do not register
  Windows tasks, call real PushPlus, import P4 modules from existing production
  entrypoints, or mark P4 complete. P1/P2 live failures preempt P4 immediately.
- P5 may proceed only as an isolated read-only dashboard replacement. Keep the
  existing port 8898 dashboard untouched until offline visual and contract
  acceptance passes; never let P5 fetch quotes, select stocks, push, trade, or
  mutate accounts. Production cutover requires separate authorization.
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

- Dashboard: `python -m v4.dashboard` at `http://127.0.0.1:8898/`
- Morning: `python v4/scripts/morning_push.py`
- Confirmation: `python v4/scripts/afternoon_push.py`
- Paper execution: `python v4/scripts/paper_trade.py buy|sell`

The Windows task names are deployment details, not ownership boundaries.
