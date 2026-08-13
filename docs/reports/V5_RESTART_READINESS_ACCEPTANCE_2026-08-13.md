# V5 restart and morning-readiness acceptance — 2026-08-13

## Corrections

- Registered `AStock-V5-Dashboard-Logon` for the read-only 8899 dashboard.
- The dashboard task has unlimited execution time, ignores duplicate instances, and retries three times after failure.
- The 08:30 preflight now performs up to three bounded native-universe refresh attempts.
- A failed preflight exits with code 3 instead of allowing Windows Task Scheduler to record a false success.
- The production static audit now requires the V5 dashboard supervisor as well as the V5 shadow task set.

## Machine evidence

- `AStock-V5-Dashboard-Logon`: registered, enabled, `PT0S`, restart count 3.
- `http://127.0.0.1:8899/api/read-model`: HTTP 200, `v5-product-read-model-v1`.
- Current data quality is intentionally `unavailable`; no V5 strict current-day facts exist and no V4 facts are projected.
- Production static audit v3: passed, V5 paper writer disabled, no broker task.
- Full repository suite: 305 passed in 99.40 seconds.

## Remaining real evidence

The 08:30 job must still demonstrate an actual native universe refresh tomorrow. Retry and exit-code behavior are accepted offline; provider availability is not inferred.
