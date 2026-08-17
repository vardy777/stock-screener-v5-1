# V5 live failure audit — 2026-08-17

## Result

The V5 decision chain failed before notification projection. PushPlus transport was healthy and accepted operational alerts, but no business notification was eligible.

## Immutable evidence

- 08:30 readiness returned success, but its one-symbol probes carried 2026-08-14 timestamps and proved transport only.
- 09:24:31 morning acquisition: Sina 4/5549 (0.0721%); Eastmoney 0/5549.
- 14:49:01 signal acquisition: Sina 5207/5549 (93.8367%); Eastmoney 2077/5549 (37.4302%).
- No morning pool, frozen snapshot, confirmation, business notification, or strict sample was created.
- All downstream dependency failures were consequences of the two rejected acquisitions.

## Root causes

1. The morning capture ran before the 09:25 call-auction result and incorrectly required current strict quotes.
2. The Eastmoney directory contained 337 codes explicitly marked delisted by Tencent, inflating the coverage denominator.
3. Eastmoney's quote endpoint did not provide complete full-market fields and was unsuitable as the second strict quote source.
4. Downstream dependency failures each emitted an alert, causing redundant noise.
5. The still-elevated V4 health task retained a legacy PushPlus failure path.

## Corrections

- Morning acquisition/push moved to 09:25:05/09:25:50.
- Universe is now Eastmoney directory intersected with Tencent's explicit active-listing status.
- Strict quote consensus is now Sina plus Tencent; Eastmoney remains the directory source.
- Offline after-close diagnostic: active universe 5212; each source returned 5203 (99.8273%); common 5203; price conflicts 0.
- Dependency-cascade alerts are suppressed; only root failures alert.
- V4 morning push, confirmation push, and health alert entrypoints are code-retired before their legacy runner.
- V4 dashboard launcher is code-retired; V5 remains on 8899.
- Dashboard now shows rejected source coverage and the latest acquisition failure instead of an uninformative empty state.

## Boundaries

- No 2026-08-17 strict fact was fabricated or backfilled.
- `research_locked` remains enabled.
- No broker order was sent.
- V5 paper writer remains disabled while the V4 paper bridge is the single writer.
- The corrected source chain still requires real 2026-08-18 window acceptance.

## Acceptance

- Focused tests: 32 passed.
- Full suite: 370 passed.
- Production static audit v4: passed.
- Nine safe V5 tasks for 2026-08-18 are registered and ready.
