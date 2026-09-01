# V5.1 Shadow Task Manifest

Status: `REPORT_ONLY / NOT AUTHORIZED / NOT REGISTERED`

Generated from the 2026-08-27 real-window preflight. This manifest does not
register Windows tasks, start a V5.1 business writer, alter port 8899, send a
notification, or create a strict market fact.

## Preflight finding

The `v5_1` package now contains an isolated Runtime (`python -m
v5_1.task_runner`) and real Sina/Tencent/Eastmoney provider adapters, alongside
its immutable repositories, isolated paper ledgers, read model and preview
dashboard. These entrypoints are offline-tested but are **not** registered in
Windows Scheduler and do not own production. Official SSE/SZSE Security Master
adapters are implemented as the exchange-authoritative base; Eastmoney is an
optional third-party cross-check. Their current real-network transport remains
unaccepted, so real-window acceptance is still pending.

Current truth: `V5.1 RUNTIME IMPLEMENTED = YES`; `V5.1 FINAL RUNTIME
ACCEPTANCE = PENDING`; `BLOCKER = REAL-WINDOW OFFICIAL MASTER + QUOTE ACCEPTANCE`.

The 2026-08-27 09:35 window was already past when this preflight began
(14:22 Asia/Shanghai). It must remain missing; no later quote may be written as
a 09:35 strict fact.

## Proposed isolated tasks (not registered)

| Task | Proposed trigger | Required output | Production interaction |
|---|---:|---|---|
| `V51-Shadow-Master-Recovery` | 08:10/08:30/08:50/09:05/09:20 | idempotent Master attempts; same successful entity is reused | V5.1 shadow root only; disabled |
| `V51-Shadow-Market-Warmup` | 09:30:00 | dual-source observation diagnostics | V5.1 fact root only |
| `V51-Shadow-Morning-Pool` | 09:35:00 | immutable 09:35 Morning Pool | V5.1 fact root only |
| `V51-Shadow-Feature-Freeze` | 14:49:00 | immutable shared freeze and pointer | V5.1 fact root only |
| `V51-Shadow-Decisions` | 14:50:00 | Baseline confirmation and CloseScan selection | V5.1 fact root only |
| `V51-Shadow-Paper-Buy` | 14:50:40 | fresh execution observations and isolated paper events | two V5.1 ledgers only |
| `V51-Shadow-Paper-Sell` | 09:30:10 next open day | fresh sell observations and isolated paper events | two V5.1 ledgers only |
| `V51-Shadow-Health` | 14:53:00 | immutable health/run/failure facts | V5.1 fact root only |
| `V51-Shadow-Acceptance` | 15:20:00 | pipeline and round-trip acceptance | read-only projection |

## Required runner boundary before authorization

The shadow runner must:

1. write only beneath a dedicated V5.1 fact root;
2. use separate Baseline and CloseScan ledger roots;
3. import no V5 notification or production-account writer;
4. never write or mutate `v5/data`;
5. never send PushPlus or broker orders;
6. enforce exchange calendar and wall-clock windows internally;
7. save immutable failure facts when a window or input gate fails;
8. reject manual `trade_date`, `observed_at`, or execution-time overrides that
   could manufacture strict evidence;
9. expose idempotent recovery without allowing a missed window to be backfilled;
10. be statically audited for one V5 production writer plus one isolated
    research-only V5.1 shadow writer.

## Authorization gate

`scripts/render_v5_1_shadow_tasks.ps1` renders this report-only definition; it
contains no task-registration command. Do not register or run the proposed
tasks until real-window provider wiring passes and the user separately
authorizes an atomic cutover. V5 remains the sole production owner. Port 8899
and all existing Windows tasks remain unchanged.

Safety state: `research_locked=true`, `broker_orders=false`.
