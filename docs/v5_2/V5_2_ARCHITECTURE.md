# V5.2 Architecture

## Chosen approach

Use a strangler-style namespace boundary: retain verified version-neutral
infrastructure in `shared_core`, build new contracts and orchestration in
`v5_2`, and leave V5.1 readable but outside the V5.2 import graph. This avoids
both risky in-place mutation of `v5_1` and a copy-everything fork that would
duplicate bugs and version ownership.

## Data flow

```text
official/persistent Security Master + TradingCalendar
  -> PIT DailySecurityStatus + DailyTradability
  -> complete D DailyBar + CorporateAction facts
  -> DatasetManifest and PIT validator
  -> deterministic Feature Engine + Market Regime
  -> explainable AlphaScore + cross-sectional RankingFact
  -> WatchlistFact (50/20/10/5)
  -> optional candidate-only D+1 confirmation/execution
  -> future LabelSet (D+1..D+5, evaluation namespace only)
  -> walk-forward EvaluationReport
```

## Component boundaries

- `facts`: frozen dataclasses/schemas, causal validation, repositories and
  content-addressed identity. No strategy logic.
- `data`: source adapters and ingestion. Raw responses and normalized facts are
  separate; adapters never decide eligibility.
- `universe`: reconstructs membership/status on D and emits inclusion/exclusion
  reasons. It never consults today's symbol list for an old date.
- `features`: consumes a validated dataset slice through D; deterministic,
  versioned transforms only.
- `labels`: consumes sessions strictly after D and is unavailable to ranking.
- `ranking`/`strategies`: computes explainable scores and stable tie-breaking.
- `evaluation`: walk-forward partitions, Top-K metrics and benchmark/regime
  reports; cannot mutate datasets or strategy parameters.
- `portfolio`/`execution`: deferred consumers; isolated from research facts.
- `dashboard`: read-only projection from immutable manifests/results.

## Proposed directory structure

```text
v5_2/
  __init__.py
  facts/{base,security_master,security_status,daily_bar,corporate_action,financial,manifests,repositories}.py
  data/{adapters,ingest,quality,pit_validation}.py
  universe/{policy,builder}.py
  features/{definitions,engine,regime}.py
  labels/{definitions,engine}.py
  ranking/{contracts,ranker}.py
  strategies/{baseline_v1}.py
  evaluation/{walk_forward,metrics,report}.py
  portfolio/
  execution/{confirmation,safety}.py
  dashboard/{read_model,server}.py
tests/v5_2/{facts,data,universe,features,labels,ranking,evaluation,governance}/
```

Directories are proposed, not created in this design phase.

## Import dependency migration graph

```text
shared_core.core/calendar/trading_calendar_contract/order_quantity/paper
       |                         |
       v                         v
v5_2.facts <- v5_2.data <- source adapters
       |
       +-> v5_2.universe -> v5_2.features -> v5_2.ranking -> WatchlistFact
       |                         |                 |
       +-------------------------+-> v5_2.labels   +-> optional execution
                                      |
                                      v
                              v5_2.evaluation -> dashboard

FORBIDDEN: v5_2 -> v5_1.runtime/decision/closescan/providers/scheduler/notifications
FORBIDDEN: ranking/features -> labels/evaluation future windows
FORBIDDEN: data/facts -> strategy/ranking
```

An AST gate will reject all `v5_1.*`, `v5.*`, realtime full-market adapter and
notification imports from the active V5.2 graph. Candidate-only confirmation
must be an optional outward consumer of a persisted WatchlistFact.

## Failure behavior

Missing lineage, duplicate/conflicting facts, future `known_at`/`available_at`,
calendar gaps, incomplete daily bars, unknown adjustment state, manifest hash
mismatch or partition overlap fail closed. The run publishes a failure fact,
not a partial ranking. Data-quality thresholds and exclusions are recorded in
the DatasetManifest.
