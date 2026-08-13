# V5 hardening acceptance — 2026-08-13

## Accepted offline changes

- Both real-time providers are captured concurrently and each is bounded by a 25-second overall budget. Paging and retry loops fail closed when the budget is exhausted.
- The 14:50 confirmation consumes only the content-addressed 14:49 frozen snapshot. It does not request the market again.
- Immutable facts select recency by timezone-aware business timestamps, never by hash filename ordering.
- `v5-daily-lineage-acceptance-v1` verifies morning/signal acquisitions, stored snapshots, frozen pointer, same-day mother pool, confirmation subset, notification payload hashes and real HTTP 200/ACCEPTED receipts.
- The 14:53 V5 health report embeds the lineage audit.
- All seven registered V5 shadow tasks for 2026-08-14 use the common immutable task runner. V5 paper buy/sell remain unregistered while V4 owns the only paper ledger writer.

## Evidence

- Focused acceptance: 24 passed.
- Full repository suite: 283 passed in 99.24 seconds.
- Project consistency command: PASS, missing=0, v3 imports=0.
- `research_locked` remains active. The 95% per-source coverage and consistency gates were not lowered. No broker order path was enabled.

## Pending real-window evidence

- Each provider must independently prove at least 95% coverage, acceptable quote age and cross-source consistency during the real 09:25 and 14:49 windows.
- Both V5 notifications must retain real PushPlus HTTP 200/ACCEPTED receipts with matching payload and parent entity IDs.
- Only after the V5 shadow chain passes may paper-ledger ownership, the full nine-task schedule and port 8898 be atomically migrated. Until then, V4 remains the sole paper writer and rollback baseline.
