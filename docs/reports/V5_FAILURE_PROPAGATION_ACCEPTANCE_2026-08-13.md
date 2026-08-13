# V5 failure propagation acceptance — 2026-08-13

## Guarantees added

- Operational failures use a dedicated PushPlus alert entity and do not replace the two business notifications.
- An operational alert is successful only with a real response code 200; rejected attempts are retained separately and remain retryable.
- Alert delivery never changes a failed business task into success.
- Morning and confirmation payloads require the acquisition snapshot ID to equal the projected entity snapshot ID.
- Notification and health readers use an `as_of` cutoff and cannot consume future facts.
- Health requires a causal V5-native universe, not merely any JSON in the same-day universe directory.
- Every safe downstream task requires immutable SUCCESS records from its upstream tasks before execution.

## Safety boundaries

- No operational alert creates candidates or prices.
- No V5 paper writer or broker operation is enabled.
- `research_locked` remains active.
- V4 remains the transitional paper writer until separate single-writer cutover evidence exists.

## Acceptance evidence

- Focused alert, notification, health, dependency and lineage suites passed.
- Full repository suite: 310 passed in 99.35 seconds.
