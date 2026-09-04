# V5.1 to V5.2 Reuse Inventory

This is the readable companion to `V5_1_REUSE_INVENTORY.json`. Counts are by
inventory item (a source module, artifact, or explicitly named file group), not
by physical file count.

| Classification | Count | V5.2 meaning |
|---|---:|---|
| KEEP | 15 | retain behavior or historical evidence; no opportunistic rewrite |
| ADAPT | 15 | reuse a proven idea behind a new V5.2 contract |
| RESEARCH_ONLY | 8 | available to offline investigation, absent from production import graph |
| DEPRECATE | 13 | readable historical code/evidence, no active ownership |
| REMOVE_FROM_RUNTIME | 9 | explicitly forbidden in V5.2 active imports/entrypoints |

## Core foundation to retain

`TradingCalendar`, strict validation, PIT identity, Security Master lineage,
daily status/tradability, content hashes, immutable atomic persistence,
release/clean-room verification, order-lot rules and the paper ledger are the
main inheritance spine. `security_master.py`, `tradability.py` and generic fact
helpers are classified ADAPT—not KEEP—because their public types and storage
paths still carry V5.1 semantics.

## Components to retire from active runtime

The retirement boundary is behavioral: full-market realtime quote providers,
MorningPool, CloseScan, strict 14:49/14:50/14:50:40 stages, mandatory D+1 open
exit, PushPlus ownership, Natural SHADOW and RC scheduler scripts. Files are not
deleted in the first migration. Import-graph tests will make the boundary
enforceable.

## Promotion to shared_core

Only generic canonical serialization, content addressing and atomic immutable
write primitives are candidates for promotion from `v5_1/facts.py`. Promotion
requires characterization tests, a version-neutral interface and proof that V5
and V5.1 behavior is unchanged. Security Master and tradability remain V5.2
adapters initially; they are not dumped wholesale into `shared_core`.

## Audit scope and limitations

The audit traversed tracked `shared_core/`, `v5_1/`, tests, docs, scripts,
configuration/release schema and release tooling. Generated caches, runtime
facts, logs, local stage directories and unrelated G1/user changes are excluded
from module counts. The classification is a migration decision, not proof that
the retained component already meets V5.2 historical coverage requirements.
