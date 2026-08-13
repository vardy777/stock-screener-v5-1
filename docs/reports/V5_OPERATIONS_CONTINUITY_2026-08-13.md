# V5 operations continuity acceptance — 2026-08-13

## Accepted changes

- 14:53 health excludes the health task that is currently executing, preventing a deterministic self-missed false alarm.
- Failed PushPlus responses are persisted under immutable attempt history. Only HTTP 200 writes the canonical accepted receipt, so retries remain possible and auditable.
- Notification copy matches the single-page dashboard: conclusion, reasons, risks, observation/confirmation distinction, frozen ask reference, next-session exit rule, no predicted sell price and no broker connection.
- Morning production refreshes the V5-native universe from the market directory before acquisition. A large count reduction or code churn fails closed against the latest prior universe.
- Universe identity now hashes the complete entity content, including date, time and sources. When seed and live universes coexist, the latest timezone-aware business entity is selected.
- A narrowly scoped administrator script defines seven safe V5 shadow tasks for 2026-08-17. It contains no paper-buy, paper-sell or broker task.

## Acceptance evidence

- Focused operations suite: 12 passed.
- Full repository suite: 291 passed in 99.08 seconds.
- `research_locked`, 95% acquisition gates, no broker orders and single paper-ledger writer remain unchanged.

## External state not yet achieved

The attempt to register 2026-08-17 tasks returned Windows `Access is denied`; the current process token is not elevated even though the user authorized administrative work. Therefore no Monday task is claimed as installed. Run the following once from an elevated PowerShell before Monday:

```powershell
cd C:\Users\lisha\stock-screener
powershell -ExecutionPolicy Bypass -File .\v5\scripts\register_safe_shadow_tasks.ps1 -TradeDate 2026-08-17
```

The script fails unless it has an administrator token and verifies all seven installed tasks before returning success.
