# V5 paper and strategy offline closure — 2026-08-13

## Material defects corrected

- The nine-task manifest declared `paper_buy` and `paper_sell`, but the sole V5 task entrypoint did not implement them.
- Paper performance was read from a `round_trips.json` file that no producer created, so the dashboard would have remained at zero forever.
- Per-symbol sizing used one third of declining cash rather than one third of initial capital.
- Orders were not persisted before fills, concurrent appends were not process-locked, and crash-pending orders could not be audited.
- Simulation ignored top-of-book depth and did not independently enforce causal buy/sell windows.
- No strict comparable baseline was produced.
- Market state was a synthetic ID rather than an immutable whole-market entity.
- Morning observation incorrectly required an executable ask; market risk-off was treated as a system fault instead of a valid empty decision.

## Offline contracts now implemented

- All nine V5 task names have executable entrypoints.
- Paper tasks require `paper_writer=v5` and `authorized=true`; current default remains V4, so double writing is impossible.
- Buy uses only the final confirmation and its 14:49 frozen snapshot; sell uses a fresh dual-source strict 09:30 snapshot.
- The local verified official exchange calendar determines T+1 and is owned under `v5/reference`.
- Initial capital is ¥100,000; each symbol is capped at one third of initial capital and available cash.
- Ask/bid depth, board lots, commission, stamp tax, slippage and T+1 are enforced.
- Orders are immutable before execution; event append is process-locked; pending orders produce an explicit recovery report.
- Round trips are derived from the hash-chained ledger and obey the dashboard `as_of` cutoff.
- The admission baseline mirrors the production Top1 exposure, one-third capital cap, same 14:49 ask reference, fees/slippage, and the same next-session 09:30 strict bid. It does not dilute Top1 results across the broader confirmed candidate set, and no closing-price proxy is used.
- `MarketStateV1` records breadth, turnover, median return, limit/halt counts and a versioned risk gate. Risk-off generates an explainable empty decision rather than an operational failure.
- Market-state hashes and snapshot lineage are checked by dashboard, PushPlus and daily health acceptance.

## Strategy conclusion

These changes make the experiment measurable; they do not prove profitability. The current strategy remains a transparent deterministic rule baseline with zero accepted live V5 round trips. Model publication and production release remain locked until strict samples, comparable baselines and walk-forward evidence exist.

## Acceptance evidence

- Full repository suite: 328 passed in 100.29 seconds.
- V5 independence audit confirms no V4/phase1 runtime imports and a valid V5-owned official calendar; full independence remains false because real facts, scheduler, paper writer and 8898 have not been cut over.
