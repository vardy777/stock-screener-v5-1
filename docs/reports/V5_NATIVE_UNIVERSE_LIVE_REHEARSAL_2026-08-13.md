# V5 native universe live rehearsal — 2026-08-13

## Result

- Eastmoney market directory declared 5,549 rows and all 56 actual 100-row pages were consumed.
- V5 eligible-board filtering produced 4,930 codes.
- The legacy seed contained 4,399 codes; all 4,399 were retained and 531 were added.
- Published V5 universe: `univ1-f1d80c0bc14bad300f72caf200616756fc2c07470d20dc93697474f38611911f`.
- Entity time: `2026-08-14T08:30:00+08:00`; sources are V5 native directory plus prior-universe anomaly gate.

## Reliability corrections

- The provider ignores the requested 500-row page size and returns 100 rows. Pagination now follows the declared total and actual rows rather than a fixed 20-page assumption.
- Access hosts rotate only after a transport failure and remain one Eastmoney provider identity; they are not misrepresented as independent sources.
- Every attempt stays within the 12-second overall preparation budget.
- The first native directory may expand the legacy seed only after retaining at least 99.5% and dropping no seed code. Later native-to-native days return to the strict 2% churn gate.
- The existing 08:30 readiness task performs this workday preparation. It remains diagnostic for quotes and cannot create strict-window evidence, send notification, write a paper account or call a broker.

## Task evidence

The 2026-08-14 V5 readiness, morning facts, morning push, feature freeze, confirmation, confirmation push, health and maintenance tasks are all present and Ready with V5 entrypoints. V5 paper buy/sell remain absent to preserve the single V4 ledger writer.

Full repository acceptance: 297 passed in 100.14 seconds.
