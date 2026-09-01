# V5.1 Production Cutover and Rollback

Status: `PENDING AUTHORIZATION`. This document is report-only; no Windows task
or port ownership has been changed.

## Runtime

Working directory: `C:\Users\lisha\stock-screener`

Python: `C:\Users\lisha\stock-screener\.venv\Scripts\python.exe`

Single entrypoint: `python -m v5_1.task_runner <task> --mode PRODUCTION_RESEARCH`

Every command uses the Runtime stage lock, immutable run/failure facts,
content-addressed outputs and idempotent successful-stage reuse. Failure is
fail-closed. Broker orders do not exist in this runtime.

| Task | Trigger | Command | Timeout/retry | Dependencies |
|---|---:|---|---|---|
| Preflight | 08:30:00 | `... task_runner preflight` | 120s; 2×60s | calendar, directory, stores, ledgers |
| Observation | 09:30:00 | `... task_runner morning_observation` | 240s; bounded provider retry | preflight |
| Morning Pool | 09:35:00 | `... task_runner morning_pool` | 40s; retry only inside 09:35:59 | observation/tradability |
| Morning notification | 09:35:45 | `... task_runner morning_notification` | ownership-gated | Morning Pool |
| Feature Freeze | 14:49:00 | `... task_runner feature_freeze` | 55s; inside window only | tradability/providers |
| Decisions | 14:50:00 | `... task_runner confirmation` | 35s; immutable no-op | morning pool/freeze |
| Confirmation notification | 14:50:30 | `... task_runner confirmation_notification` | ownership-gated | confirmation |
| Paper Buy | 14:50:40 | `... task_runner execution` | 15s; quote age ≤5s | decisions |
| Paper Sell | next open 09:30:10 | `... task_runner next_open_exit` | 15s; quote age ≤5s | recoverable positions |
| Health | 14:53:00 | `... task_runner health` | 60s | read-only stage facts |
| Acceptance | 15:20:00 | `... task_runner acceptance` | 120s | immutable daily chain |
| Round-trip acceptance | next open 09:31+ | `... task_runner round_trip_acceptance` | 120s | next-open exit + reconciled closed ledgers |

The final task definitions must set: battery allowed, wake enabled,
start-when-available **disabled for strict windows**, three retries only while
the runtime window remains open, and one common V5.1 working directory. Missed
strict windows write failure facts and never backfill.

## Current legacy ownership

- production owner: V5
- dashboard 8899: `python -m v5.dashboard`
- morning tasks: 09:25:05 and 09:25:50
- V5 is the only current paper/notification writer

## Atomic target

- production owner: V5.1
- dashboard 8899: `python -m v5_1.dashboard --port 8899 --data-dir v5_1/data`
- morning pool: 09:35:00
- morning push: 09:35:45 (enabled only with V5.1 ownership manifest)
- `research_locked=true`; `broker_orders=false`

## Authorized cutover sequence (future only)

1. Export exact legacy task definitions and ownership file.
2. Disable every V5 business writer, paper task and notification task.
3. Verify no enabled/running V5 writer and no V5.1 writer exists yet.
4. Install V5.1 tasks disabled; audit commands, triggers and working directory.
5. Atomically update ownership manifest to V5.1 and enable V5.1 tasks.
6. Verify exactly one research-production writer and two strategy-isolated
   ledgers governed by that runtime.
7. Stop legacy 8899 dashboard and start V5.1 8899 read-only dashboard.
8. Smoke-test routes, task audit, ownership, locks and broker prohibition.

At no point may V5 and V5.1 business writers overlap.

The D-day `acceptance` row is preliminary only. It is prohibited from creating
strict-day credit. `round_trip_acceptance` on D+1 is the sole final authority.

Current decision: **NOT CUTOVER READY**. V5 remains production owner; Windows
Scheduler and port 8899 are unchanged. V5.1 real-window strict days: 0.
Official SSE/SZSE independent Master adapters and real single-source diagnostics
pass; a natural-window full cross-source SHADOW verification remains pending.
Strategy effectiveness: `UNPROVEN`.

Runtime implementation is present, but final Runtime acceptance remains pending
the first natural-window cross-source SHADOW fact and full-day evidence.
Eastmoney-only operation cannot pass this gate.

## Rollback

1. Disable all V5.1 tasks and verify no V5.1 runtime remains.
2. Stop V5.1 dashboard on 8899.
3. Restore the exported V5 ownership manifest and exact V5 task definitions.
4. Start V5 dashboard on 8899 and rerun production/static audits.
5. Leave all V5.1 facts and ledgers immutable and read-only; never copy them
   into V5 or rewrite their strategy/system identity.

Rollback is operational only and does not turn missed windows into strict
evidence.
