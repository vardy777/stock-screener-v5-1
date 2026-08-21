# V5 production review — 2026-08-21

## Verdict

V5 has not completed one correct full production day. Its offline contracts and tests are substantial, but the product cannot yet be called operationally accepted or strategically effective.

## Immutable production evidence

- 2026-08-18: readiness, morning pool and morning PushPlus succeeded. The receipt is HTTP 200 / ACCEPTED.
- 2026-08-18: 14:49 feature freeze failed. Sina signal coverage was 91.71%; Tencent coverage was 99.85% but the strict quality contract rejected it. Confirmation and the second push therefore did not complete.
- 2026-08-19, 2026-08-20 and 2026-08-21 morning: no V5 run artifacts, candidate facts or notification receipts exist.
- Root cause of the multi-day outage: production registered dated one-day tasks only. There was no recurring task continuity after 2026-08-18.
- The V4-labelled message was emitted by a legacy V4 health task before its notification entrypoint was retired. V4 notification and dashboard entrypoints are now code-gated, but V4 paper compatibility tasks remain installed as the sole existing paper writer bridge.

## Repairs made

- Added nine recurring weekday V5 tasks with exchange-calendar enforcement in the runtime.
- Kept the recurring chain free of paper and broker tasks.
- Added exchange-calendar enforcement to readiness and every V5 task entrypoint.
- Extended immutable acquisition diagnostics with source rejection reasons, quote age and batch duration, and projected those reasons on the V5 dashboard.
- Made daily live acceptance infer the current China trade date for recurring execution.
- Updated production static audit to accept and inspect the recurring chain.
- Replaced the stale V4 project-state document with a factual V5 state.

## Acceptance evidence

- Full automated suite: 371 passed, 0 failed.
- Production scheduled-task static audit: passed.
- Nine recurring safe tasks: installed and Ready.
- V5 dashboard task: supervised and running on port 8899.
- V5 PushPlus token file: present; this does not count as delivery evidence.

## Remaining gates

- A full real trading day from 08:30 readiness through 15:20 acceptance has not passed.
- The next required full-window acceptance is 2026-08-24.
- Both 09:25 and 14:50 notifications must each have an immutable HTTP 200 / ACCEPTED receipt.
- The 14:49 dual-source capture must pass strict coverage, freshness and consistency without relaxed thresholds.
- Strict simulated round trips remain zero, so strategy effectiveness and profitability are unproven.
- V5 paper writer was activated at 12:12 after proving both ledgers contained zero events and no positions. V4 business entrypoints are code-retired because their protected OS definitions cannot be disabled by the current token.

## Midday production hardening

- Corrected the quote clock model: provider response time now controls whole-batch freshness; a symbol's last-trade exchange time no longer invalidates the entire market.
- Added a 120-second per-symbol last-quote gate so stale symbols cannot enter the funnel.
- Real 2026-08-21 diagnostic: 5,215-symbol universe, 5,205 quotes from each source, 99.808% coverage, zero price conflicts, zero time conflicts, consensus accepted.
- Corrected morning-pool and frozen-pointer causal timestamps to follow snapshot completion.
- Reduced scheduler restart interval from two minutes to one minute and enabled start-when-available.
- Retired every V4 business adapter before any V4 market or execution import, preventing simultaneous V4/V5 full-market requests.
- Activated the V5-only paper buyer and seller; the recurring production manifest now has eleven tasks and no broker action.
- Added immutable sell acquisition/consensus lineage and snapshot-completion execution time.
- Repaired a Windows atomic-replace sharing race in the V5 event ledger; the concurrent append test passed 30 consecutive stress iterations.
- Full suite after repairs: 375 passed, 0 failed.
