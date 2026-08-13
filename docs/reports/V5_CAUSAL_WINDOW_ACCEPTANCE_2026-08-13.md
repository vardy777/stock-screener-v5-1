# V5 causal universe and task-window acceptance — 2026-08-13

## Defects found and corrected

- A native universe generated during a future-dated rehearsal could have been selected tomorrow as if it were an 08:30 production fact. The exact rehearsal artifact was removed.
- Universe selection previously used latest business time but did not reject facts created after the consumer's `as_of` time.
- Market jobs previously accepted a same-day legacy migration seed if native preparation failed.
- Windows `StartWhenAvailable` could launch a missed strict task outside its trading window because the Python entrypoint had no independent time gate.

## Enforced contracts

- `morning_pool` and `feature_freeze` require a causal, same-day, V5-native universe sourced from `eastmoney_realtime_market_directory`.
- A future universe cannot satisfy a current consumer.
- Same-day migration seeds remain usable only as refresh ancestry, never as production market-job input.
- Morning acquisition, both notifications, feature freeze, confirmation, health, and maintenance each have explicit allowed windows in the single V5 entrypoint.
- A late task records an immutable failed run and performs no market fetch or notification.

## Acceptance evidence

- Focused causal/window/notification/schedule suite: 23 passed.
- Full repository suite: 301 passed in 100.12 seconds.
- `git diff --check`: passed (line-ending notices only).
- `research_locked` remains active; no broker task or V5 paper writer was enabled.

## Still requires real-window evidence

- A genuinely created 08:30 native universe fact.
- Real dual-source 09:24:30 and 14:49 coverage, latency, and consistency.
- Real 09:25 and 14:50 PushPlus HTTP 200/ACCEPTED receipts.
- Same-day mother-pool-to-confirmation lineage and next-session simulation evidence.
