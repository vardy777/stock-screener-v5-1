# V5 morning-window budget acceptance — 2026-08-13

## Contract correction

The daily universe directory refresh is preparation, not one of the nine trading-business tasks. It is scheduled at 08:30. The 09:24:30 `morning_pool` job only consumes the frozen same-day V5 universe and captures the two quote sources. This avoids repeating the Eastmoney directory request immediately before the quote request and preserves the 50 seconds available before the 09:25:20 notification.

## Failure-closed guarantees

- Universe pagination has a 12-second overall budget.
- Each request timeout is capped by the remaining overall budget.
- An empty page before the declared total is reached is rejected as incomplete pagination.
- Prior-universe count and churn anomaly gates remain mandatory.
- A missing 08:30 universe fact causes `morning_pool` to fail; it never silently reuses an older trade date.
- Shadow run records use atomic create-once writes and immutable collision checks.

## Evidence

- Window-budget and dashboard focused suite: 8 passed.
- Full repository suite: 293 passed in 99.43 seconds.
- The prepared administrator manifest contains eight safe tasks for 2026-08-17: one universe preparation plus seven V5 shadow tasks. It contains no paper or broker action.
- Windows task registration remains externally pending because the current process token was denied administrator access; this report does not claim installation.
