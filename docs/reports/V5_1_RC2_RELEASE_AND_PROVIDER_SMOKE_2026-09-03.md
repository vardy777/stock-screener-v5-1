# V5.1-RC2 Release Freeze and Provider Smoke — 2026-09-03

## Decision

- `RC1 = INVALIDATED`
- `RC1 ARTIFACT UNCHANGED = YES`
- `RC2 OFFLINE CODE & CONTRACT READINESS = PASS`
- `RC2 CLEAN-ROOM ACCEPTANCE = PASS`
- `RC2 RELEASE FREEZE GATE = PASS`
- `TONIGHT OFFICIAL MASTER SMOKE = FAIL`
- `RC2 NATURAL SHADOW ENTRY = NO-GO`
- `real_window_strict_days = 0`

The RC2 code and release artifact are frozen and suitable for independent code
review. They are **not** authorized for Natural SHADOW because the full SSE
official directory request did not complete within the observed smoke budget.
No source threshold, uniqueness rule or time gate was relaxed.

## Root cause repaired

RC1 erased SSE share-category identity before uniqueness validation. The 44
duplicate A-code groups in the 2026-09-02 response were individually inspected:
all 44 are official `STOCK_TYPE=1` / `STOCK_TYPE=2` A/B category variants, and
zero groups remain unexplained. RC2 deterministically selects the sole official
A-share category row and preserves excluded source-row lineage. Unknown shapes
and genuine current-identity conflicts still fail closed.

## Evidence and tests

- incident full-response SHA-256: `0b980fb8cabff9cbba6980a4c5a5a4539767d8c227f5affa1962729ff554cbbe`
- observed incident shape: raw 2,516; parsed 2,506; unique A symbols 2,462;
  duplicate groups 44
- RC2 canonicalization tests: `17 passed`
- all V5.1 tests: `159 passed`
- repository suite after integration: `666 passed in 109.64s`
- clean-room release-only acceptance: `PASS` (68 release files verified)
- clean-room V5.1 suite: `159 passed`
- clean-room import provenance: `shared_core` and `v5_1` both loaded only from
  `C:\Users\lisha\V5_1_RC2_CLEANROOM_12992a2`
- compileall: `PASS`
- direct `v5_1/shared_core -> v5.*` runtime imports: `0`
- V5 independence audit: `PASS`
- production task audit: `FAIL` only because existing V4 compatibility OS tasks
  are not all disabled; each enabled legacy task was reported code-guarded and
  runtime-safe. This RC2 repair was forbidden from changing Scheduler ownership.

## Immutable release identity

- release ID: `V5.1-RC2`
- source commit: `12992a22ae0cacc1a1a5160fdf46d7c6c28fbfc8`
- integrated master commit: `01417650c5e75925ba10021c89de082ada226d93`
- common git tree: `b220df7b75d920e5b5fe75c33bc320ee14083c81`
- artifact: `C:\Users\lisha\stock-screener\V5_1_RC2.zip`
- artifact SHA-256: `493feeea08130e6d2779a7c2377651aab3dade83ebdb3e527de5bfe86932726b`
- release manifest SHA-256: `4d95829f1fa5f9fca58da156b23be5b183aefa002e150db258d97210852924b7`
- dependency lock SHA-256: `464f8f36eec063d26dfdad3ae4095f03a93b7f19d9ac19c0ae22d808c411fa32`
- source inventory file SHA-256: `f28a6f108f293821321fa70d7c6e921b1fd65344008f60e316ce48f368d3b3ec`
- source manifest semantic hash: `1fc1db94a780ef118c87487e164a012116dd87350f25914cabbb9d47f7eb587b`
- config hash: `00b05d20f0c88205d8cf7037a81b38b47e98cb1c3e04ac1dea4b17b9b53729f2`
- RC1 artifact SHA-256 reverified unchanged:
  `092a83feb2a8b8bdf22404df409836100910197d7c9513f6338658bfc0c333c4`

The release scope was clean at build time. The main repository remains dirty
only from pre-existing, unrelated G1/V5 work outside this RC2 release scope.

## Frozen provider smoke

At `2026-09-03T08:17:20+08:00`, the non-strict two-source quote smoke for
`600000` passed:

- Sina: HTTP transport OK, bid 9.28 / ask 9.29, positive depth
- Tencent: HTTP transport OK, bid 9.28 / ask 9.29, positive depth
- coverage: 1.0
- result: `PASS`

The official Master smoke did not pass:

- SZSE official source: `PASS`, 2,899 rows, 2,899 unique symbols, elapsed 4.719s,
  response SHA-256 `e464340bc022c51c2cf5fad92ec0504ebe5911326678dd5aad3c5944efaea0a3`
- SSE full official request: `FAIL`, full 5,000-page-size response timed out in
  a direct adapter run; the subsequent frozen preflight produced no output for
  more than four minutes and was operator-cancelled as a smoke timeout
- official combined Master: `FAIL`
- freshness: `NOT REACHED`
- preflight: `FAIL`

Smaller official SSE pagination blocks were reachable and supplied the 44-group
classification evidence, but RC2 does not silently replace its frozen full
request with an unreviewed pagination change. That delivery behavior requires a
separate reviewed release candidate.

## Safety state

- `production_owner = V5`
- `production_cutover_authorized = false`
- `research_locked = true`
- `broker_orders = false`
- Windows Scheduler modified: `NO`
- port 8899 ownership modified: `NO`
- V5 production facts/ledger modified: `NO`
- notification ownership modified or notifications sent: `NO`
- `CUTOVER READY = NO`
- `PRODUCTION RESEARCH GO = NO`
- `BROKER LIVE TRADING GO = NO`
- strategy effectiveness: `UNPROVEN`

## Required next action

Stop here for independent ChatGPT review. Do not start Natural SHADOW. The next
candidate must add a bounded, deterministic SSE pagination transport contract
with total-count conservation, page identity/ordering checks, duplicate-boundary
handling and timeout/retry evidence, then repeat offline, clean-room and provider
smoke gates under a new immutable identity.
