# V5 unattended runtime acceptance — 2026-08-13

## Machine findings

- AC sleep is disabled; battery sleep is configured at ten minutes.
- V5 scheduled tasks originally disallowed start on battery and could not wake the machine.
- The V5 PushPlus environment exists and contains a configured token; the token value was not printed.

## Corrections applied

- All current V5 preflight and shadow tasks now allow start and continued execution on battery.
- All current V5 preflight and shadow tasks now have `WakeToRun=true`.
- The reusable registration manifest applies the same battery and wake policy.
- Native-universe preparation is consistently scheduled at 08:30, not 08:55.
- Static production audit fails when any active V5 business/preflight task lacks battery or wake readiness.

## Boundaries

- No V4 task, paper ledger writer, broker task, or research gate was changed.
- Wake readiness does not prove provider availability or HTTP 200 notification delivery; those remain real-window evidence.
