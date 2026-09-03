# V5.1-RC1 Invalidation Record — 2026-09-02

## Decision

- `RC1 = INVALIDATED`
- `reason = SSE Security Master CODE/DATA-CONTRACT BUG`
- `2026-09-02 Natural SHADOW = FAIL`
- `real_window_strict_days = 0`
- `no_backfill = true`
- `no_hotfix_rc1 = true`

The frozen RC1 Security Master contract rejected the live SSE official directory
after parsing because the result contained duplicate symbols. The fail-closed
response was correct, but the frozen release cannot model the real official SSE
record shape and therefore cannot continue Natural SHADOW.

## Frozen incident evidence

- Day 1 report: `docs/reports/V5_1_RC1_NATURAL_SHADOW_DAY1_2026-09-02.md`
- Root-cause report: `docs/reports/V5_1_RC1_DAY1_ROOT_CAUSE_DIAGNOSTIC_2026-09-02.md`
- Root-cause report canonical Git-content SHA-256:
  `89e45e68d7f10426b5a6871fe73bc2bf421c5c18223f468bb5932ad324a2f1eb`
- Evidence commit:
  `238e46666bc7bd86a76904f29d43a564a1f14340`
- Frozen release ID: `V5.1-RC1`
- Frozen source commit:
  `14cbcf2615a68a50789997e26527f82074a2ca6e`
- Frozen source tree:
  `985930b9bc0786393004d8e3ab76d83286537b54`
- Frozen artifact SHA-256:
  `092a83feb2a8b8bdf22404df409836100910197d7c9513f6338658bfc0c333c4`

The root-cause report's checked-out file SHA may differ under Git's CRLF
checkout conversion. The value above is computed from the exact committed blob
content (`git show 238e466:<path>`), which is the canonical evidence boundary.

## Operational disposition

- All 14 `V51-RC1-Shadow-*` tasks are disabled.
- No missed stage may be manually caught up.
- No 2026-09-02 strict evidence may be backfilled.
- RC1 must remain byte-for-byte unchanged.
- Any repair must produce a separately built and frozen `V5.1-RC2` candidate.
- V5 remains the production owner.
- `research_locked=true`.
- `broker_orders=false`.
- Production scheduler ownership, notification ownership, port 8899 and the V5
  production ledger remain unchanged.

## Gate

`INCIDENT EVIDENCE FROZEN = PASS`

This record authorizes no production cutover and makes no claim of strategy
effectiveness.
