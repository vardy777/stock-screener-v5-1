# V5 causal clock gate — 2026-08-13

## Defect

The V5 charter said the causal clock contract was reused, but V5 only detected clock problems indirectly after downloading provider quotes. It did not verify Windows Time and external NTP offset before strict capture.

## Correction

- Added a V5-native gate that requires W32Time running, a synchronized non-CMOS source, at least two external NTP measurements, and maximum absolute offset no greater than 0.5 seconds.
- The gate runs in the 08:30 preflight and immediately before both 09:24:30 and 14:49 market capture.
- Failure stops the task before contacting quote providers and uses the independent operational alert path.
- The 0.5-second threshold was not relaxed.

## Current machine evidence

- W32Time service: running.
- Source: synchronized to `ntp.aliyun.com`.
- Four consecutive three-sample measurements: failed, approximately 0.615–0.618 seconds maximum absolute offset.
- `scripts/repair_windows_time.ps1` was attempted but Windows rejected it because this process has a medium-integrity, non-elevated token. Starting the privileged built-in synchronization task was also denied.

The machine is therefore correctly marked not ready for strict capture until an elevated Windows session runs:

```powershell
cd C:\Users\lisha\stock-screener
powershell -ExecutionPolicy Bypass -File .\scripts\repair_windows_time.ps1
```

No strict fact is manufactured and `research_locked` remains active.

## Acceptance

- Focused clock/preflight/task suite: 8 passed.
- Full repository suite: 312 passed in 100.11 seconds.
