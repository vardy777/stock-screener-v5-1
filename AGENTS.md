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
- Preserve user-owned untracked files and unrelated worktree changes.

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
