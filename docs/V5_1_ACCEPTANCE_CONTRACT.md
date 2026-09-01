# V5.1 Overnight Acceptance Contract

Status: offline implementation accepted locally; natural-window evidence pending.

## PreliminaryDayAcceptance(D)

Created after D 15:20 from the complete same-day pipeline. It proves data,
decisions, BUY execution or legitimate flat outcome, ledger and health lineage.
Its exit and round-trip fields are always `PENDING`, its real-window state is
`PRELIMINARY_ONLY`, and it is never strict-day credit.

## RoundTripAcceptance(D)

Created only after the next open session. A traded day must reconstruct each
round trip through candidate, confirmation/selection, BUY execution observation,
BUY paper event, position decision, next-open exit decision, SELL execution
observation, SELL paper event, closed position and reconciled PnL. Strategy,
symbol, decision, event and trade dates must agree; ambiguity, missing entities,
duplicates, tampering, open positions or count mismatch fail closed.

An ACTIVE_FLAT day has zero candidates/trades only after a successful D pipeline
and successful D+1 no-position observation. Missing data, source failure,
execution failure or a missed task can never be reclassified as ACTIVE_FLAT.

Only a content-addressed PASS `RoundTripAcceptance` is eligible to increment
strict-day evidence. Current strict natural round-trip day count remains zero.
