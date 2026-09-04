# V5.2 Phase 0 and Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans` to
> implement this plan task-by-task after architecture approval. Track each
> checkbox and review each gate independently.

**Goal:** Establish a reproducible PIT historical-data and deterministic
research foundation without activating V5.2 trading or realtime full-market
runtime.

**Architecture:** V5.2 is a new namespace over a retained `shared_core` spine.
It consumes immutable manifest-linked facts, separates features from future
labels, and leaves all V5.1 realtime choreography historical.

**Tech stack:** Python standard library/dataclasses/Decimal/zoneinfo, pytest,
JSON schemas/manifests, Git content identity.

**Spec:** `docs/v5_2/V5_2_PRODUCT_SPEC.md`, `V5_2_ARCHITECTURE.md`,
`V5_2_DATA_CONTRACTS.md`, `V5_2_RESEARCH_PROTOCOL.md`.

## Global constraints

- Architecture must receive independent ChatGPT approval before execution.
- Preserve RC1/RC2 bytes and Git history; do not commit on dirty `master`.
- Keep `research_locked=true`; no broker, orders, PushPlus or task registration.
- No `v5_2` dependency on V5.1 runtime or full-market realtime sources.
- Every task uses test-first, fail-closed behavior and a focused commit on a
  dedicated `v5.2-development` or `feature/v5.2-foundation` branch/worktree.

## Phase 0 — History and governance

### Task 0.1: Freeze and assert V5.1 history

**Files:** create `tests/v5_2/governance/test_v51_retirement.py`; update no RC
artifact. The test asserts the two SHA256 values, retirement status strings and
that the inventory counts equal its items. Run the targeted test, then the
existing V5.1 release-artifact tests. Commit only governance/docs.

### Task 0.2: Create the V5.2 namespace boundary

**Files:** create `v5_2/__init__.py` and
`tests/v5_2/governance/test_import_boundaries.py`. First write an AST test that
fails if active `v5_2` imports `v5`, `v5_1`, PushPlus, scheduler registration or
the three full-market realtime adapters. Add only the package version and make
the test pass.

### Task 0.3: Characterize generic immutable fact primitives

**Files:** test `v5_1/facts.py` behavior in
`tests/v5_2/facts/test_legacy_fact_characterization.py`; then create
`shared_core/facts.py` and `tests/v5_2/facts/test_immutable_facts.py`. Assert
canonical Unicode/key ordering, deterministic ID, atomic create-once,
idempotent identical write and rejection of conflicting overwrite. Do not
redirect V5/V5.1 imports until compatibility tests pass.

**Phase 0 gate:** clean targeted suites, unchanged ZIP hashes, zero forbidden
imports, and explicit evidence that no scheduler/notification/runtime state was
changed.

## Phase 1 — Historical PIT foundation

### Task 1.1: Define base facts and repositories

Create `v5_2/facts/base.py` and `repositories.py` with strict aware-time,
Decimal, source-lineage and content-ID validation. Tests cover naive/future
time, duplicate business keys, conflicting payloads and tampering before adding
the minimum implementation.

### Task 1.2: Adapt Security Master and daily status

Create `security_master.py`, `security_status.py` and tests for interval
overlap, listing/delisting boundaries, later-delisted inclusion, historical ST,
suspension, new listing and unknown status. Import adapters may call legacy
parsers, but persisted V5.2 facts use only V5.2 types and IDs.

### Task 1.3: Implement DailyBarFact

Create `daily_bar.py` and tests for OHLC invariants, Decimal precision,
prev-close/limit consistency, zero-volume suspension, source uniqueness,
availability and raw/adjusted separation. No vendor downloader is part of this
task.

### Task 1.4: Implement corporate actions and adjustment views

Create `corporate_action.py`, `v5_2/data/adjustments.py` and tests for cash,
split/share, rights, revisions, ex-date, late publication and as-of adjustment.
Add a golden case proving a later-known action cannot alter an earlier feature
snapshot.

### Task 1.5: Build the PIT universe

Create `universe/policy.py`, `universe/builder.py` and tests reconstructing a
past date without consulting current listings. Golden fixtures must include a
later-delisted stock, historical ST, suspension, not-yet-listed symbol and
missing-status fail-close. Output inclusion plus reason-coded exclusions.

### Task 1.6: Create DatasetManifest and quality gate

Create `facts/manifests.py`, `data/quality.py`, `data/pit_validation.py` and
tests for stable content hashes/counts, source inventory, calendar/master
versions, duplicate/future facts, reproducibility and tamper rejection. The
manifest is published only after PIT status PASS.

### Task 1.7: Create feature and label engines

Create versioned definitions/engines and formula-specific tests for the Phase 1
feature list and all required labels. Add a structural test that feature/ranking
packages cannot import labels. Use exchange-session offsets and explicit
censoring; test same-bar first-passage ambiguity.

### Task 1.8: Create deterministic baseline ranking

Create `strategies/baseline_v1.py`, ranking contracts/ranker and tests for
component math, missingness, regime adjustment, risk penalties, stable symbol
tie-breaks and exact nested 50/20/10/5 tiers. Label values must not affect a
ranking hash.

### Task 1.9: Implement walk-forward evaluation

Create split, metric and report modules. Tests reject random/overlapping or
reverse-time splits and verify Top-K mean/median, hit/precision, benchmark
excess, drawdown, MAE/MFE, turnover, capacity, sector concentration and regime
slices against hand-computed fixtures.

### Task 1.10: Reproducibility and clean-room acceptance

Create a fixture-scale end-to-end run twice in separate temporary roots and
assert identical dataset, feature, label, ranking and evaluation hashes. Add a
V5.2 release verifier that scans forbidden imports and secrets but does not
build an RC or register tasks. Run targeted tests, full offline suite and a
clean-room extraction test; record exact evidence.

**Phase 1 exit gate:** all contract gates pass and an out-of-sample evaluation
is complete. The final verdict may be `ALPHA FOUND` or `ALPHA NOT FOUND`.

## Explicitly deferred

Realtime confirmation, dashboard polish, paper execution, ML, broker/live
trading and physical deletion/movement of V5.1 code are separate post-gate
plans. No task above authorizes them.

## Migration risks and P0 blockers

- Existing current-universe utilities are not survivorship-safe.
- No verified complete historical DailyBar/corporate-action source inventory is
  established by this architecture work.
- V5.1 PIT contracts prove semantics but not multi-year coverage or vendor
  adjustment correctness.
- Dirty `master` prevents a safe mixed commit; implementation needs an isolated
  branch/worktree preserving current user changes.
- Alpha thresholds cannot be frozen until coverage/quality profiling, but must
  be frozen before locked-test access.

`READY FOR IMPLEMENTATION = NO` until independent architecture review approves
the contracts, migration boundary and research protocol.
