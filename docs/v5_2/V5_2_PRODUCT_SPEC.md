# V5.2 Product Specification

## Purpose

V5.2 is an after-close A-share full-market alpha-research and swing-candidate
engine. Using only facts legally known by the close of trade date D, it ranks an
eligible point-in-time universe for outcomes over the next 1-5 trading days.
It produces Watchlist 50, Top 20, Top 10 and Top 5. It does not promise that a
stock rises tomorrow and may conclude `ALPHA NOT FOUND`.

## Product contract

Primary run time is after D close, after the complete daily bar and required
status facts have an explicit `available_at <= run_as_of`. Output targets are:

- `P(up within 1d|3d|5d)` and `P(breakout within 5d)` when a calibrated model
  is eventually approved;
- deterministic baseline scores and rank explanations in Phase 1;
- expected return at 1/3/5 trading days, 5-day maximum upside/drawdown, and
  first-passage `+3% before -2%` / `+5% before -3%` labels.

The first baseline is explainable: trend + breakout + relative strength +
volume + liquidity + regime adjustment - volatility - drawdown/risk penalty.
It is a score, never labeled as a probability.

## Required outputs

Every formal run publishes immutable, cross-linked `DatasetManifest`,
`ResearchRunManifest`, `FeatureSnapshot`, `LabelSet` (evaluation only),
`RankingFact`, `WatchlistFact` and `EvaluationReport`. A daily production ranking
must not expose future labels.

## Eligibility and exclusions

Eligibility is reconstructed for D from the PIT Security Master and daily
status/tradability facts. It includes historically listed securities—including
later-delisted names—and explicitly records exclusions for not-yet-listed,
delisted, suspended, ST/risk-warning, new-listing seasoning, missing/invalid bar
or insufficient liquidity. Policy versions determine whether ST/new listings
are excluded; data is never silently dropped.

## Optional D+1 confirmation

An independently deployable later layer may query only the 20-50 ranked
symbols to check suspension, extreme gap, one-price limit, price deviation,
bid/ask viability and abnormal market risk. It is an execution filter, cannot
change AlphaScore using the rest of the market, and cannot become a full-market
realtime scanner.

## Non-goals and hard gates

No broker/live capital, automatic orders, deep learning, LLM prediction,
news/social sentiment, tick/Level-2 data, intraday crawler, HFT optimization or
complex portfolio optimizer. `research_locked=true` and broker orders remain
disabled. P0 data correctness precedes candidate results.

Phase 1 exits only when Historical PIT Dataset, survivorship safety, corporate
actions, DailyBar contract, deterministic features/labels, walk-forward
isolation, baseline completion and out-of-sample evaluation all pass. The
verdict is exactly `ALPHA FOUND` or `ALPHA NOT FOUND`; the latter stops strategy
expansion.
