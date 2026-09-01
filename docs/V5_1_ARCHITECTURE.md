# V5.1 Architecture

## Status and boundary

`V5.1 OFFLINE RUNTIME REPAIR PASSED / REAL-WINDOW ACCEPTANCE PENDING / NOT CUTOVER READY`.
V5 remains the production scheduler owner until a separately authorized atomic
cutover. V5 facts are read-only legacy evidence. V5.1 facts must carry
`system_version=5.1`, a V5.1 strategy version and `contract_version` and live
under a separate fact root. `research_locked=true`; broker orders are disabled.

## Product flow

```text
Persistent Security Master + completed verification cycle
  -> same-day Daily Security Status
  -> deterministic Daily Tradability
  -> 09:30-09:34 observation
  -> 09:35 Baseline Morning Pool
  -> shared strict 14:49 full-market Decision Snapshot
       -> Baseline confirmation (same 09:35 pool only)
       -> CloseScan selection (full market; no pool dependency)
  -> 14:50:40+ independent Execution Snapshot
  -> isolated paper ledgers
  -> D 15:20 PreliminaryDayAcceptance (never increments strict-day evidence)
  -> next-session 09:30+ independent sell Execution Snapshot
  -> position/ledger reconciliation and deterministic round-trip reconstruction
  -> RoundTripAcceptance(D) (the only strict-day acceptance authority)
  -> STRICT-only paired comparison
```

## Persistent Security Master

The master stores append-only symbol versions with exchange, board, name,
listing/delisting dates, validity interval, point-in-time `known_at` and source
lineage. A verification-cycle fact is separate. Freshness means a successful
current or previous completed exchange-session verification cycle; it is not an
arbitrary wall-clock duration. A failed morning directory request does not erase
the master. `require_fresh(trade_date, as_of, calendar)` derives the only allowed
dates from the verified production `TradingCalendar`; business callers cannot
provide or expand an allowed-date list. The repository also
requires `verified_at <= as_of`, resolves every referenced master version and
validates version validity and source lineage. Missing the allowed cycle,
content tampering, future lineage or independent-source conflict fails closed.

SSE and SZSE official lists form the authoritative base Master for their own
exchanges. Eastmoney hosts form one `eastmoney` provider family and are an
optional third-party cross-check, never a discovery prerequisite. Both official HTTP adapters were
successfully diagnosed on 2026-08-30 (2,505 and 2,897 valid records
respectively). Symbol, exchange, strictly normalized name and listing date must
match when third-party data is available; a conflict fails closed. Eastmoney
transport failure is recorded as `DEGRADED_THIRD_PARTY_UNAVAILABLE` and does
not discard a complete official base. Official-source outage, invalid identity,
duplicate symbol or content-address mismatch fails closed. Eastmoney alone can
never satisfy Master verification. Directory responses and per-symbol matches
are immutable content-addressed facts referenced by the verification fact.
BSE remains excluded by contract.

Report-only SHADOW recovery definitions exist at 08:10, 08:30, 08:50, 09:05
and 09:20. They are disabled and not installed; a prior successful immutable
preflight is reused idempotently, while tampering causes fail-closed recovery.

## Daily status and tradability

Daily facts express ST, suspension, delisting period, new listing and ambiguous
or unknown status. Each status is append-only under
`daily_security_statuses/<trade_date>/<symbol>/<status_id>.json`. Tradability
resolves stored status IDs, master-version IDs and verification ID before
publication. Wrong day, future `known_at`, missing, duplicate or conflicting
lineage fails closed. Boolean inputs must be real JSON/Python booleans.
For every supplied status, Tradability additionally asks the repository for the
unique as-of fact for that date/symbol. A second stored fact therefore cannot be
hidden by passing only one of the two facts.

## Evidence versions

- V5 legacy baseline: immutable, displayed only as legacy history.
- V5.1 baseline: `v5.1-baseline-0935-v1`; frozen V5 weights and risk thresholds,
  but a new evidence cohort because the observation moved to 09:35.
- CloseScan: `v5.1-closescan-v1`; explainable full-market 14:49 challenger.
- STRICT and PROXY cohorts remain physically/logically separate.

## Decision and execution

The 09:35 decision window is 09:35:00–09:35:59 and its accepted snapshot may be
at most 30 seconds old. The shared feature snapshot must complete inside
14:49:00–14:49:59 and have an immutable snapshot plus freeze pointer.
Execution observations require a different accepted snapshot and enforce
`decision_time < execution_observation_time <= execution_time`; the observation
may be at most 5 seconds old at fill. Buy requires a fresh ask and
`buy_execution`; sell requires a fresh bid and `sell_execution`. Halt, limit,
depth, session or time failures reject execution.

CloseScan persists independent candidate/funnel, selection and run facts, then
uses its own execution observations, paper root and STRICT comparison. It shares
read-only market/tradability inputs and never reads a Morning Pool.

## Dashboard scope

The V5.1 dashboard has distinct `/today`, `/candidates`, `/validation`,
`/account` and `/health` pages. It projects only V5.1 Baseline and CloseScan.
G1 is intentionally absent but its independent project/files remain untouched.
The implementation is offline-complete on preview port 8901. Port 8899 remains
the legacy V5 production dashboard and is not switched by offline development.
The V5.1 HTTP dashboard uses `ImmutableReadModelBuilder`, which accepts only a
fact root and trade date and reconstructs state from content-addressed run,
failure, confirmation, selection, execution-observation and execution-result
facts. Arbitrary caller dictionaries are not a production dashboard source.

## Migration and rollback

Build and rehearse V5.1 in isolation, validate a real shadow window, audit the
report-only scheduler change, then request explicit authorization for an atomic
8899/task ownership switch. Rollback restores V5 task definitions and leaves all
V5.1 facts read-only; neither direction rewrites historical evidence.

Stable calendar, contract, market-data, source, funnel, quantity and paper-ledger
primitives now live in the version-neutral `shared_core` package. Both V5 and
V5.1 import that same canonical implementation; V5 modules are compatibility
aliases, not a second business implementation. An AST gate and an isolated-copy
test require zero `v5.*` imports in `v5_1` and prove V5.1 imports with only
`v5_1 + shared_core` present. This closes the source dependency gate but does
not authorize production ownership or cutover.
