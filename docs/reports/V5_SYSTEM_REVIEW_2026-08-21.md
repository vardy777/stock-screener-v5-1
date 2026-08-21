# V5 production review — 2026-08-21

## Verdict

V5 has not completed one correct full production day. Its offline contracts and tests are substantial, but the product cannot yet be called operationally accepted or strategically effective.

## Immutable production evidence

- 2026-08-18: readiness, morning pool and morning PushPlus succeeded. The receipt is HTTP 200 / ACCEPTED.
- 2026-08-18: 14:49 feature freeze failed. Sina signal coverage was 91.71%; Tencent coverage was 99.85% but the strict quality contract rejected it. Confirmation and the second push therefore did not complete.
- 2026-08-19, 2026-08-20 and 2026-08-21 morning: no V5 run artifacts, candidate facts or notification receipts exist.
- Root cause of the multi-day outage: production registered dated one-day tasks only. There was no recurring task continuity after 2026-08-18.
- The V4-labelled message was emitted by a legacy V4 health task before its notification entrypoint was retired. V4 notification, paper and dashboard entrypoints are now code-gated; V5 is the authorized single paper writer. Several ACL-protected V4 task definitions remain installed but cannot reach business implementations.

## Repairs made

- Added nine recurring weekday V5 tasks with exchange-calendar enforcement in the runtime.
- Kept the recurring chain free of paper and broker tasks.
- Added exchange-calendar enforcement to readiness and every V5 task entrypoint.
- Extended immutable acquisition diagnostics with source rejection reasons, quote age and batch duration, and projected those reasons on the V5 dashboard.
- Made daily live acceptance infer the current China trade date for recurring execution.
- Updated production static audit to accept and inspect the recurring chain.
- Replaced the stale V4 project-state document with a factual V5 state.

## Acceptance evidence

- Full automated suite: 377 passed, 0 failed.
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

## 13:01 same-day recovery evidence

- The scheduled recovery task did run at 13:01, but retained an immutable failed result (`LastTaskResult=3`): frozen candidate mappings were not JSON serializable. Its failure alert received a real PushPlus HTTP 200 / ACCEPTED response.
- The serialization path was corrected by projecting the immutable funnel through its versioned dictionary contract. A success-path regression test now persists candidates and verifies an accepted receipt.
- A separate in-window rerun at 13:02 succeeded. Both independent sources returned 5,205 of 5,215 symbols (99.808% coverage); the cross-source consistent ratio was 99.751%; the observation notification received HTTP 200 / ACCEPTED.
- The recovery observation is explicitly non-strict (`strict_0925_sample=false`) and ineligible for confirmation or paper execution. It does not repair or pretend that the missing 09:25 production window occurred.
- Full suite after the recovery repair: 380 passed, 0 failed.
- Corrected downstream alert suppression: a dependency gap is silent only when an immutable upstream failure record contains an accepted alert. A task that never ran now causes one actionable alert instead of a silent downstream cascade.
- Corrected the dashboard recovery projection so `candidate_count`, rendered items and both complete source identities agree. The supervised 8899 process was restarted and returned HTTP 200 with 5/5 candidates and two sources.
- Corrected machine-readable runtime status to report the latest 2026-08-21 non-strict recovery fact instead of the older 2026-08-18 morning pool.
- Made health and maintenance observational tasks independent of business-task success. They now always persist diagnostics/maintenance evidence; a failed health report retains its checks and emits one accepted operational alert.
- Made a valid empty confirmation an explicit `NO_CANDIDATE` paper success with no ledger event. A no-op trading day can now complete operational acceptance without pretending that a fill occurred.
- Added confirmation content-hash verification before both filled and no-candidate paper paths.
- Full suite after task-graph and empty-day repairs: 383 passed, 0 failed.
- Live acceptance now requires both V5 paper tasks; a day cannot pass while simulated execution is missing.
- Added the orphan-signal dashboard state: after a valid 14:49 freeze without a strict 09:25 mother pool, the page projects the latest tail market state, clears recovery candidates and explicitly forces no confirmation/no paper buy.
- Full suite after live-acceptance and tail-projection repairs: 384 passed, 0 failed.
- The prior production task audit enumerated only seven legacy names and missed eight ACL-protected V4 tasks that remain `Ready`. Audit v7 now inventories every `AStock-V4-*` task and reports OS retirement separately from code-gated runtime safety.
- Current truth: not every V4 OS task is disabled, but every remaining Ready business task invokes the retired adapter that exits before importing any market, decision, notification or paper implementation. The V4 dashboard task is now disabled; a privileged process started on 2026-08-16 still owns 127.0.0.1:8898 and the current desktop token receives Access Denied when terminating it. Port 8899 remains the supervised V5 product.

## Real 14:49 tail window

- The recurring feature-freeze task ran at 14:49:00 and exited 0. The causal clock gate passed with a 40 ms maximum measured offset.
- Both sources returned 5,205 of 5,215 symbols (99.808% coverage). Cross-source consistency was 99.770%; two symbols had price conflicts; consensus was accepted without changing any threshold.
- Frozen snapshot `ms1-6a844da95a02d0a70840391162d4a05721b13dca5888c44f636d6d71ca381a03` completed at 14:49:09 and was published through an immutable pointer.
- Confirmation failed closed because the strict 09:25 mother pool was missing. Exactly one dependency alert received HTTP 200 / ACCEPTED; confirmation push and paper buy preserved failed run facts and suppressed duplicate alerts. No confirmation, notification receipt, order or paper event was fabricated.
- A production defect was exposed: feature freeze did not persist its market-state entity because that derivation previously lived only inside confirmation. The dashboard correctly returned 503 rather than fall back, then recovered after deterministic derivation from the immutable frozen snapshot. Feature freeze now persists market state itself; no morning pool, candidate, confirmation or fill was backfilled.
- The repaired dashboard returned HTTP 200 with `accepted_no_morning_pool`, 0 candidates, both source identities, the 14:49 snapshot and a forced-empty-position explanation.
- The 14:53 health task ran independently, retained all failed checks and received a separate HTTP 200 / ACCEPTED health alert. Native universe, paper reconciliation/recovery, exclusive writer and due-position exit checks passed.
- Full suite after the live defect repair: 385 passed, 0 failed.

## Final 15:10 / 15:20 evidence

- The recurring maintenance task ran at 15:10 and exited 0. Manifest `maint1-da6b931ed243dbf66643bb4b` validated 113 JSON files and found no invalid file.
- The recurring live-acceptance task ran at 15:20. It persisted `liveacc1-e618bf9dcfd2439efcf7ee86` with no readiness or run validation errors.
- The acceptance result is truthfully incomplete because the strict 09:25 mother pool, morning notification and complete decision lineage do not exist for this date. Exit code 3 is the required fail-closed outcome, not a scheduler failure.
- All 11 recurring V5 tasks point to 2026-08-24 for their next applicable run. Production static audit v7 and V5 independence audit pass.
- Full suite after the status-reader compatibility repair: 388 passed, 0 failed.

## Final offline integrity hardening

- Runtime dependency checks, accepted-alert suppression and missed-run recovery now rebuild every run content address, require the declared ID to match its filename and reject wrong schema/task/date facts.
- The latest valid attempt for each task is authoritative. An earlier success can no longer unlock a downstream notification after a later failed attempt.
- The recurring-task description now states the actual boundary: V5 local paper execution is allowed, while broker orders and V4 writes are forbidden.
- Power and host readiness were checked: 1,206 GiB free, Windows Time running automatically, AC sleep disabled, V5 dashboard supervised on 8899, and all 11 tasks configured to wake, start when available, ignore overlapping instances and retry within their unchanged strict windows.
- Full suite after runtime dependency hardening: 391 passed, 0 failed.
