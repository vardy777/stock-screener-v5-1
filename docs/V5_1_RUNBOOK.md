# V5.1 Runbook

Offline dashboard preview: `python -m v5_1.dashboard --port 8901`. This is not
the production 8899 owner. Inspect Security Master freshness, daily-status
coverage and failed component before any strategy fact. A missing/ambiguous
status, stale verification cycle, bad dual-source snapshot or broken lineage is
`FAIL_CLOSED`, never `ACTIVE_FLAT`. Legal complete-chain empty decisions are
`ACTIVE_FLAT`. Do not repair a missed window with old universes or later quotes.

Hard timing contracts: Master verification must exist as-of the caller; the
09:35 snapshot age is at most 30 seconds; the shared decision snapshot and
freeze pointer must be immutable and inside 14:49:00–14:49:59; execution quotes
must be post-decision, use the correct book side/session and be at most 5 seconds
old at fill. Daily statuses must first exist under
`daily_security_statuses/<date>/<symbol>/`; all verification/version/status IDs
must resolve before Tradability is published.
The Master freshness window is calculated only by the verified production
calendar as the current open session plus its previous completed open session.
Do not pass date lists from business code. Dashboard state must be built through
`ImmutableReadModelBuilder(v5_1_data_root).build(trade_date)`; invalid IDs or
missing execution lineage produce a quarantined `FAIL_CLOSED` projection.

The report-only scheduler plan is printed by `python -m v5_1.scheduler_plan`.
It must be reviewed and separately authorized before task registration.
The manifest records legacy 09:25:05/09:25:50 and proposed V5.1
09:35:00/09:35:45 triggers. Windows tasks remain unchanged.

The unique runtime CLI is `python -m v5_1.task_runner <task>`. `SHADOW` and
`PRODUCTION_RESEARCH` use the actual aware China-market clock and V5.1 fact
root; `REPLAY` and `TEST` must use a separate non-STRICT root. The runtime owns
one stage lock and governs the two strategy-specific paper ledgers. Current
Scheduler and notification ownership remains V5 pending atomic authorization.

The Runtime task list includes ownership-gated `morning_notification` and
`confirmation_notification`. Until an explicit atomic ownership manifest is
installed, both fail closed and cannot send. Success requires HTTP 200,
PushPlus provider code 200, and explicit accepted semantics. Tokens are read
only from ignored sensitive configuration/environment and are never facts.

## Two-stage overnight acceptance

Run `acceptance` at D 15:20. It produces only a content-addressed
`PreliminaryDayAcceptance(D)` with `real_window_acceptance=PRELIMINARY_ONLY`,
`next_open_exit_acceptance=PENDING`, and `round_trip_acceptance=PENDING`.
It must never increment a strict-day counter. After the next open session's
strict 09:30 SELL/no-position observation, run `round_trip_acceptance`. That
task validates the preliminary run, execution stage, candidate/decision, BUY
observation/event, position lineage, exit decision, SELL observation/event,
closed ledger, reconciliation, round-trip count and PnL. Only its immutable
PASS fact may count D as a strict day. A legitimate `ACTIVE_FLAT` day requires
a successful full D pipeline and a successful D+1 no-position observation;
source or task failure is not flat.

Offline release verification is one command:
`python -m v5_1.production_acceptance --release-only`. The command without
`--release-only` intentionally remains non-zero until natural-window,
Scheduler, single-writer, rollback and cutover gates all pass.

Current status: `V5.1 RUNTIME IMPLEMENTED = YES`; the official SSE/SZSE Master
adapter code and real source diagnostics pass. `V5.1 FINAL RUNTIME ACCEPTANCE`
remains pending the first natural full SHADOW window and cross-source run.
Windows Scheduler and 8899 are unchanged;
V5 remains production owner; V5.1 real-window strict days are zero; strategy
effectiveness is `UNPROVEN`. Eastmoney transport failed closed at page 5 in the
2026-08-30 diagnostic and therefore no cross-source verification fact was
published.
