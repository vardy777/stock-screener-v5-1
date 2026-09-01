# V5.1 Runtime Repair — 2026-08-28

Status updated 2026-08-30: `RUNTIME CODE READY / REAL SHADOW PREFLIGHT PENDING WINDOW / NOT CUTOVER READY`.

The previous adapter-code blocker is closed. Eastmoney-only remains
fail-closed; the remaining acceptance item is a natural-window full
cross-source SHADOW run. `research_locked=true`,
`broker_orders=false`, V5 remains production owner.

## Non-strict provider diagnostics

Recorded around 10:39–10:45 Asia/Shanghai. These observations are diagnostics,
not STRICT evidence.

- Eastmoney directory: request failed after 21.266 seconds with
  `RuntimeError: universe page 1 unavailable: URLError`; records and excluded
  identity counts were therefore unavailable. Provider family remains exactly
  `eastmoney`; `official_independent_source=false`.
- Sina, 600000: transport OK, coverage 1.0, quote timestamp
  `2026-08-28T10:45:41.086904+08:00`, bid 9.01 × 188000, ask 9.02 × 85000,
  latency 1.344 seconds.
- Tencent, 600000: transport OK, coverage 1.0, quote timestamp
  `2026-08-28T10:45:42.900735+08:00`, bid 9.01 × 188000, ask 9.02 × 85000,
  latency 1.812 seconds.

## SHADOW preflight

Command: `python -m v5_1.task_runner preflight --mode SHADOW`.

Result: exit code 1, truthful `V5.1 preflight outside actual window` at
10:39:20 Asia/Shanghai. No missed strict window was backfilled. Even within the
window, final Runtime acceptance remains blocked until an independent official
Master path exists.

## Offline verification

- V5.1 targeted tests: 86 passed.
- Repository tests: 593 passed.
- Windows Scheduler unchanged.
- Port 8899 unchanged.
- V5 facts and ledger unchanged.
- No real notification or broker order sent.

## Official Master diagnostics — 2026-08-30

These were real non-strict HTTP diagnostics and did not write Master or strict
production facts.

- SSE official list: HTTP 200, 2,515 source rows, 2,505 valid identity rows,
  10 rows excluded for missing identity metadata, elapsed 7.328 seconds.
- SZSE official XLSX: HTTP 200, 2,897 valid identity rows, no missing identity
  metadata, elapsed 4.578 seconds.
- Eastmoney discovery: failed closed at directory page 5 after 75.594 seconds
  (`HTTPError`); zero cross-source verification facts were published.
- The runtime default is now Eastmoney discovery plus the symbol's relevant
  official exchange (`sse` or `szse`). Code/exchange/name/listing-date mismatch,
  official outage, Eastmoney-only, or same-family aliasing fails closed. BSE is
  explicitly excluded.
