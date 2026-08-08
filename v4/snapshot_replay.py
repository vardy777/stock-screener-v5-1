"""Deterministic P2 replay starting at immutable MarketSnapshotV1 files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .candidate_journal import CandidateJournal
from .decision_service import DecisionChainService, execution_directive
from .market import analyze_market
from .market_gateway import SnapshotRepository
from .runtime import V4Runtime
from .replay_contracts import FeatureContextV1
from .selection import V4CandidateSelector


def replay_frozen_chain(
    morning_path: Path | str,
    confirmation_path: Path | str,
    feature_context_path: Path | str,
    *, journal_directory: Path | str,
    runtime: V4Runtime | None = None,
) -> dict:
    repository = SnapshotRepository()
    morning_snapshot = repository.load(morning_path)
    confirmation_snapshot = repository.load(confirmation_path)
    feature_context = FeatureContextV1.load(feature_context_path)
    if morning_snapshot.trade_date != confirmation_snapshot.trade_date:
        raise ValueError("replay snapshots must share trade_date")
    if morning_snapshot.session != "morning" or confirmation_snapshot.session != "buy":
        raise ValueError("replay requires morning then buy snapshot")
    if feature_context.trade_date != morning_snapshot.trade_date:
        raise ValueError("feature context trade_date mismatch")
    journal = CandidateJournal(Path(journal_directory))
    engine = runtime or V4Runtime()
    service = DecisionChainService(journal, engine)

    morning_time = datetime.fromisoformat(morning_snapshot.batch_completed_at)
    confirmation_time = datetime.fromisoformat(
        confirmation_snapshot.batch_completed_at
    )
    if datetime.fromisoformat(feature_context.feature_as_of) > confirmation_time:
        raise ValueError("feature context is non-causal")
    if runtime is None:
        engine.candidate_selector = V4CandidateSelector(
            context_rows=feature_context.previous_context,
            context_metadata={
                "strict_context_ready": True,
                "expected_previous_session": feature_context.expected_previous_session,
            },
            frozen_features=feature_context.confirmation_features,
            feature_context_id=feature_context.context_id,
            previous_context_id=feature_context.previous_context_id,
        )
    morning_market = analyze_market(
        morning_snapshot, reference_time=morning_time, persist=False
    )["market_state"]
    morning_candidates = engine.evaluate_universe(
        morning_snapshot, market_state=morning_market, decision_stage="morning",
        reference_time=morning_time,
        persist_diagnostics=False,
    )
    morning_candidates = [
        dict(item, input_context_id=feature_context.previous_context_id)
        for item in morning_candidates
    ]
    morning = service.publish_morning(
        morning_snapshot.trade_date, morning_candidates, morning_market,
        captured_at=morning_snapshot.batch_completed_at,
    )
    allowed = set(morning.get("candidate_codes", []))
    confirmation_market = analyze_market(
        confirmation_snapshot, reference_time=confirmation_time, persist=False
    )["market_state"]
    confirmation_candidates = engine.evaluate_universe(
        confirmation_snapshot, market_state=confirmation_market,
        allowed_codes=allowed,
        morning_candidates=list(morning.get("candidates", [])),
        decision_stage="confirmation",
        reference_time=confirmation_time,
        persist_diagnostics=False,
    )
    confirmation_candidates = [
        dict(item, input_context_id=feature_context.context_id)
        for item in confirmation_candidates
    ]
    decision = service.publish_confirmation(
        confirmation_snapshot.trade_date, confirmation_candidates,
        confirmation_market, decided_at=confirmation_snapshot.batch_completed_at,
        persist_diagnostics=False,
    )
    directive = execution_directive(decision)
    return {
        "replay_kind": "frozen-market-snapshot-v1",
        "morning_snapshot_id": morning_snapshot.snapshot_id,
        "confirmation_snapshot_id": confirmation_snapshot.snapshot_id,
        "feature_context_id": feature_context.context_id,
        "previous_context_id": feature_context.previous_context_id,
        "morning_pool": morning,
        "confirmation_decision": decision,
        "dashboard_projection": {"decision_id": decision["decision_id"], "outcome": decision["outcome"]},
        "push_projection": {"decision_id": decision["decision_id"], "outcome": decision["outcome"]},
        "execution_projection": directive,
    }
