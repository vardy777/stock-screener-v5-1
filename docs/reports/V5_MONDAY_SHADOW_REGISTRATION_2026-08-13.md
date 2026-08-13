# V5 Monday shadow registration — 2026-08-13

- Registered seven V5 safe shadow tasks for 2026-08-17.
- The existing daily 08:30 preflight is the sole native-universe preparation writer; the Monday manifest no longer creates a second 08:30 universe job.
- All seven tasks run as the current interactive user at limited integrity, allow battery operation, and can wake the machine.
- No V5 `paper_buy`, `paper_sell`, broker task, or V4 write is registered.
- Static audit now evaluates the nearest future trading-date cohort and requires exactly one instance of each safe task kind.
- Current nearest-date (2026-08-14) production static audit passed; Monday tasks are installed and ready for their later cohort.
