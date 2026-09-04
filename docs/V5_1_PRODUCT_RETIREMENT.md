# V5.1 Product Retirement Record

Status date: 2026-09-04  
Decision: approved product-direction change

## Formal status

```text
V5.1 PRODUCT DEVELOPMENT = STOPPED
V5.1 PRODUCTION CUTOVER = ABANDONED
V5.1 REALTIME NATURAL SHADOW PROGRAM = CLOSED
V5.1 STRATEGY EFFECTIVENESS = UNPROVEN

ENGINEERING FOUNDATION = RETAINED
PRODUCT DIRECTION = RETIRED
```

V5.1 is not a failed system. Its offline contracts, immutable evidence, release
verification and clean-room work remain useful engineering assets. The retired
part is the product objective: a full-market 14:49 snapshot, a seconds-bound
14:50 decision/execution sequence, and a mandatory next-open exit. That route
depends on full-market realtime transport and narrow provider windows without
having established strategy effectiveness.

## Frozen history

Repository: `https://github.com/vardy777/stock-screener-v5-1.git`  
Branch: `master`  
Recorded HEAD: `b7480eb09d3b8e09777ef7bb0f493fb4c59d2e7c`  
Recorded tree: `2c2d6818b462c71e1fab131d972933df9bcc37d6`

| Artifact | Required SHA256 | Verified 2026-09-04 |
|---|---|---|
| `V5_1_RC1.zip` | `092a83feb2a8b8bdf22404df409836100910197d7c9513f6338658bfc0c333c4` | unchanged |
| `V5_1_RC2.zip` | `493feeea08130e6d2779a7c2377651aab3dade83ebdb3e527de5bfe86932726b` | unchanged |

These artifacts are immutable historical evidence. V5.2 must not rebuild,
replace or relabel either archive.

The working tree was dirty when this record was prepared. Existing modified and
untracked files are user-owned and are not part of this retirement change.

## Retained engineering foundation

- Trading-calendar validation and exchange-session semantics.
- Point-in-time identity, `known_at`/validity concepts and causal checks.
- Persistent Security Master, daily status and tradability contracts, subject
  to V5.2 contract adaptation and historical-coverage validation.
- Content-addressed immutable facts, atomic persistence, source lineage and
  tamper detection.
- Release manifests, dependency scanning and clean-room verification.
- Paper-ledger and order-quantity primitives as optional later execution
  infrastructure, not as evidence of alpha.
- Tests that protect these reusable contracts.

## Retired product capabilities

The 09:35 MorningPool, 14:49 full-market CloseScan, 14:50 confirmation,
14:50:40 execution choreography, D+1 mandatory open exit, Natural SHADOW strict
day machinery, RC1/RC2 operational scheduling and full-market Sina/Tencent
realtime dependence leave the V5.2 active runtime. Historical code and evidence
remain readable. The first migration deactivates imports and ownership rather
than physically deleting files.

## V5.2 inheritance rule

V5.2 is an after-close, full-market, point-in-time research and swing-candidate
engine. It may depend on version-neutral stable infrastructure in `shared_core`
and on deliberately adapted contracts, but must not import the V5.1 runtime or
its retired time choreography. Optional D+1 realtime access is restricted to
the already-ranked 20-50 symbols and acts only as an execution-safety filter.

The authoritative module-by-module disposition is
`docs/v5_2/V5_1_REUSE_INVENTORY.json`; the readable rationale is its Markdown
companion.
