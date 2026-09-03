# V5.1-RC2 SSE Transport Diagnostic — 2026-09-03

## Decision

`CASE C: FULL REQUEST AND PAGINATION ARE BOTH UNSTABLE`

- `FULL REQUEST ROOT CAUSE = PROVIDER_OR_NETWORK_INSTABILITY_UNRESOLVED`
- `RC2 VALIDITY = UNRESOLVED`
- `RC2 INVALIDATED = NO`
- `RC3 REQUIRED = NO`
- `NATURAL SHADOW ENTRY = NO-GO`

This is a diagnostic result, not strict evidence. It did not write V5.1 SHADOW
state, preflight success, trading facts or production state.

## Frozen RC2 full-directory attempts

The exact RC2 endpoint, query fingerprint, headers, 8-second adapter timeout,
two adapter attempts and clean-room runtime were used.

1. Attempt 1: **FAIL** after 35.922 seconds; `TimeoutError` while waiting for
   HTTP response/read completion; no parseable payload.
2. Attempt 2: **PASS** in 5.218 seconds; HTTP 200, 2,877,394 bytes, 2,516 raw
   rows, 2,506 parsed rows, 2,462 unique symbols, 44 known category groups and
   2,316 current canonical records.
3. Attempt 3: **FAIL**; no result after the external bounded observation period
   exceeding four minutes, then operator-cancelled without producing runtime
   evidence.

One success between two failures is not stable recovery and does not satisfy
CASE A.

## Pagination investigation

The endpoint exposes `total=2516`, `pageCount=26` and a five-page response cache.
With requested `pageSize=100`, block-end page numbers 5, 10, 15, 20, 25 and 26
returned logical blocks of 500, 500, 500, 500, 500 and 16 rows.

The first diagnostic crawl completed:

- total conservation: 2,516 = sum of all six blocks;
- provider `NUM` sequence: exactly 1 through 2,516;
- unique source-row composite keys: 2,516;
- transport duplicates: 0;
- page gaps: 0;
- repeated first block semantic hash: identical;
- one block required one retry.

However, a second complete crawl exhausted three attempts during a read and did
not complete. Therefore pagination is supported but is not yet shown to be
operationally stable. The provider reports `sort=null`; a probe attempting an
explicit `NUM` sort did not establish a valid supported sorting contract.

Because both transport forms remain unstable, the evidence does **not** satisfy
CASE B. Implementing pagination now would violate the instruction that fixed
ordering and repeatable pagination be proved before RC3 development.

## Required answers

- Full request occasionally succeeds: **YES**.
- Full request stably recovers: **NO**.
- Full request repeatedly times out/hangs: **YES**.
- Pagination supported: **YES**.
- One complete pagination crawl conserved all rows: **YES**.
- Pagination repeatedly stable: **NO**.
- Provider total count available: **YES**.
- Explicit provider sort established: **NO** (`sort=null`).
- Same block repeat stable in the successful crawl: **YES**.
- Cross-page source-row duplication in successful crawl: **0**.
- Missing rows/gaps in successful crawl: **0**.
- Cross-crawl drift status: **UNRESOLVED**, because the second crawl failed.
- Failure layer: HTTP response/read; DNS vs connect vs TLS was not implicated by
  the successful requests, but the existing urllib API cannot separate response
  header wait from body read timeout precisely.

## Safety state

- RC2 artifact unchanged: **YES**
- RC3 created: **NO**
- `research_locked=true`
- `broker_orders=false`
- `production_owner=V5`
- `production_cutover_authorized=false`
- `real_window_strict_days=0`
- Scheduler changed: **NO**
- 8899 changed: **NO**
- notifications sent or ownership changed: **NO**
- production facts or ledgers changed: **NO**
- Natural SHADOW started: **NO**

## Next gate

Stop for ChatGPT review. A later bounded diagnostic should first establish an
officially supported deterministic ordering or a formally accepted verified
ordinal contract, and demonstrate at least two complete conserved crawls. Only
then may CASE B and a narrowly scoped RC3 be considered.
