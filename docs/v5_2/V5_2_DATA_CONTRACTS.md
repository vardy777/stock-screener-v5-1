# V5.2 Data Contracts

## Common invariant

Every fact has `schema_version`, stable business key, immutable `fact_id`,
`known_at` or `available_at`, `source_family`, `source_record_id`, payload hash
and ingestion timestamp. IDs are hashes of canonical semantic payloads. Times
are timezone-aware. A formal run accepts only facts available at its declared
`as_of`; revisions append new facts and never rewrite old ones.

## Fact schemas

### SecurityMasterFact

`symbol, exchange, board, security_name, listing_date, delisting_date,
valid_from, valid_to, known_at, source_family, source_record_id`.
Business key: `(symbol, valid_from, source_record_id)`. Validity intervals for a
symbol cannot overlap after reconciliation.

### DailySecurityStatusFact

`trade_date, symbol, is_st, is_risk_warning, is_suspended, is_delisting_period,
is_new_listing, is_tradable, reason_codes, known_at, source_family,
source_record_id`. Exactly one reconciled status per `(trade_date, symbol,
as_of)`; ambiguity fails closed and remains visible.

### DailyBarFact

`symbol, trade_date, open, high, low, close, volume, amount, prev_close,
upper_limit, lower_limit, adjustment_mode, adjustment_factor_id, available_at,
source_family, source_record_id`. Prices are positive decimals; `low <=
open/close <= high`; volume/amount are non-negative; limits and `prev_close`
must agree with board/status policy within declared tolerances. Raw and adjusted
series are distinct; no adjusted value overwrites raw history.

### CorporateActionFact

`symbol, published_at, available_at, ex_date, kind, cash, share_ratio, rights,
source_family, source_record_id, revision_of`. Adjustments may use the action
only when `available_at <= as_of`; published revisions append.

### FinancialDisclosureFact

Reserved contract: `symbol, metric, period_end, published_at, available_at,
revision_marker, value, unit, source_family, source_record_id`. Eligibility is
based on `available_at`, never `period_end`.

### DatasetManifest

`dataset_id, schema_version, created_at, as_of, source_inventory_hash,
security_master_version, calendar_version, start_date, end_date, symbols,
fact_counts, data_quality, content_hashes, pit_validation_status,
corporate_action_policy_version, universe_policy_version`. It references an
ordered content-hash set; recreating the same dataset produces the same
`dataset_id` even if run time differs.

### ResearchRunManifest

`run_id, dataset_id, strategy_version, feature_version, label_version,
training_range, validation_range, test_range, forward_range, hyperparameters,
code_commit, config_hash, created_at, random_seed, environment_lock_hash`.
Ranges are trading-session ranges and cannot overlap.

### FeatureSnapshot

`feature_snapshot_id, dataset_id, trade_date, symbol, as_of, feature_version,
values, missingness, input_fact_ids, calculation_hash`. All input dates are
`<= trade_date`; all availability times are `<= as_of`.

### LabelSet

`label_set_id, dataset_id, anchor_trade_date, symbol, label_version,
future_session_ids, future_return_1d, future_return_3d, future_return_5d,
future_max_return_5d, future_max_drawdown_5d,
breakout_20d_high_within_5d, hit_plus_3_before_minus_2,
hit_plus_5_before_minus_3, censoring_reason, input_fact_ids`.
The first-passage convention uses executable next-session opens/highs/lows as
specified by `label_version`; same-bar upper/lower ambiguity is censored, not
optimistically resolved.

### RankingFact

`ranking_id, run_id, trade_date, symbol, eligible, exclusion_reasons,
alpha_score, rank, component_scores, feature_snapshot_id, tie_break_key`.
Ranks use descending score then canonical symbol; identical inputs reproduce
the same order.

### WatchlistFact

`watchlist_id, ranking_id, trade_date, generated_at, tiers, members,
explanations, policy_version`. `tiers` contains exact 50/20/10/5 cuts when the
eligible universe permits; each smaller tier is a subset of the larger.

### EvaluationReport

`evaluation_id, run_id, split_id, generated_at, k_values, horizons, metrics,
benchmark_versions, regime_slices, sector_concentration, capacity,
turnover, verdict, evidence_hashes`. Required metrics include mean/median
return, hit rate, precision@K, excess return, drawdown, MAE/MFE, turnover,
capacity/liquidity, sector concentration and regime stability for K=5/10/20/50.

## Adjustment and causal policy

Feature series use a declared as-of adjustment view assembled from corporate
actions already available at the anchor time. Labels use economically
consistent returns but never feed adjusted future knowledge back into features.
Suspended future sessions are handled by explicit censoring/trading-session
rules. No forward-fill creates a tradable price.
