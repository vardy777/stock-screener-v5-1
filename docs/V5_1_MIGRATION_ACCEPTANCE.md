# V5.1 Migration Acceptance

## Offline gates

- [x] Version boundary and independent namespace.
- [x] Append-only PIT Security Master and as-of verification lineage.
- [x] Stored Daily Status/tradability lineage and strict booleans.
- [x] 09:35 Morning Pool with fixed 30-second decision-age gate.
- [x] Immutable 14:49 freeze and separate decision/execution observations.
- [x] Fixed 5-second execution quote-age gate for buy and sell.
- [x] Independent CloseScan candidate/run/selection facts and paper roots.
- [x] STRICT-only paired statistics and agreement metrics.
- [x] Multi-page dashboard contract with no G1 projection.
- [x] Report-only scheduler migration plan.
- [ ] Real SSE/SZSE endpoint acceptance.
- [ ] Second independent external review of the corrected implementation.
- [ ] Explicit authorization to alter Windows tasks and port 8899.

## Required live-window gates

1. Master and allowed verification cycle are valid before market open.
2. Same-day status is complete and unambiguous.
3. 09:30–09:34 Sina/Tencent observations stabilize.
4. 09:35 creates one immutable V5.1 pool with coverage/freshness/consensus.
5. 14:49 creates a shared full-market decision snapshot.
6. 14:50 creates independent Baseline confirmation and CloseScan selection.
7. 14:50:40+ creates a different executable buy snapshot for each selected code.
8. Next open creates a causal 09:30+ sell snapshot and reconciled fills.
9. PushPlus and dashboard project the same final V5.1 baseline entity.
10. 15:20 reports system, Baseline and CloseScan states separately.

Until all live gates pass, the authoritative state is:

`V5.1 OFFLINE ACCEPTANCE PASSED / NEXT REAL TRADING WINDOW PENDING`.
