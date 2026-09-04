# V5.2 Research Protocol

## Preregistration and reproducibility

Before evaluation, freeze dataset, universe, feature, label, strategy,
benchmark and metric versions in a ResearchRunManifest. A result is formal only
if dataset hashes, code commit, config hash and environment lock reproduce.
Exploratory runs are labeled `EXPLORATORY` and cannot support an alpha verdict.

## Causal boundary

For anchor D, features may use D close and earlier facts only when their
`available_at <= as_of_after_close(D)`. Labels use D+1 through D+5 exchange
sessions. The ranking process has no import/API access to label storage. A PIT
validator rejects future timestamps, unresolved revisions and content hashes
outside the manifest.

## Walk-forward splits

Random train/test split is prohibited. The first usable plan, conditional on
coverage, is train 2018-2022, validation 2023, locked test 2024, forward 2025
and shadow 2026. If coverage differs, partitions move only by a preregistered
rule: contiguous full sessions, training before validation before test before
forward, with no overlap. Model/weight choices stop after validation; test and
forward are each evaluated once per frozen strategy version.

For deterministic baseline v1, training estimates no opaque model. Validation
selects from a small preregistered grid of component weights/eligibility
thresholds; test remains untouched. A later ML phase requires a new protocol.

## Features and labels

Baseline features are limited to documented price returns, gaps/ranges/close
location, MA levels/slopes/alignment, distance/new-high/breakout, volume and
amount ratios, ATR/realized/range volatility, market/industry relative strength,
drawdowns, liquidity and daily market regime. Every formula declares lookback,
minimum observations, missing-value behavior and input price convention.

Labels follow `V5_2_DATA_CONTRACTS.md`. Trading-day calendar, suspension,
delisting and same-bar threshold ambiguity produce explicit censoring. Corporate
actions use the frozen adjustment policy.

## Evaluation

For every horizon and K=5/10/20/50 report mean and median return, hit rate,
precision@K, CSI300/CSI500/broad-market excess return, portfolio drawdown,
5-day MAE/MFE, turnover, liquidity/capacity, sector concentration and regime
stability. Report confidence intervals or block-bootstrap uncertainty without
turning statistical significance into a profitability guarantee.

Multiple comparisons are logged. Any feature/weight change after seeing test
creates a new exploratory lineage and cannot reuse the old test verdict.

## Verdict rule

`ALPHA FOUND` requires preregistered out-of-sample criteria to pass across
returns, risk, costs/capacity and stability; the exact numeric thresholds are
frozen only after data coverage profiling and before locked-test access.
`ALPHA NOT FOUND` is mandatory if the frozen criteria fail. It stops strategy
expansion; no feature accumulation is allowed to rescue the verdict.

## P0 research gates

PIT leakage, calendar correctness, DailyBar correctness, corporate actions,
survivorship, delisted/ST/suspended handling, duplicate facts, future
availability and dataset reproducibility must pass before strategy metrics are
treated as evidence. Feature/label correctness, isolation and ranking
determinism are P1. Dashboard/presentation is P2.
