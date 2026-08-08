"""Single P2 publication path used by live orchestration and frozen replay."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .candidate_journal import CandidateJournal


class DecisionChainService:
    def __init__(self, journal: CandidateJournal, runtime):
        self.journal = journal
        self.runtime = runtime

    def publish_morning(
        self, trade_date: str, candidates: Iterable[dict], market_state: dict, *, captured_at=None
    ) -> dict:
        self.journal.save_morning(trade_date, candidates, market_state, captured_at=captured_at)
        return self.journal.morning(trade_date)

    def publish_confirmation(
        self, trade_date: str, candidates: Iterable[dict], market_state: dict, *,
        decided_at=None, persist_diagnostics: bool = True,
    ) -> dict:
        linked = self.journal.link_confirmation_candidates(trade_date, candidates)
        reference_time = (
            datetime.fromisoformat(str(decided_at)) if decided_at is not None else None
        )
        evaluated = self.runtime.evaluate_candidates(
            linked, market_state, reference_time=reference_time,
            persist_diagnostics=persist_diagnostics,
        )
        self.journal.save_confirmation(trade_date, evaluated, market_state, decided_at=decided_at)
        return self.journal.confirmation(trade_date)

    def publish_missing_morning(self, trade_date: str, market_state: dict) -> dict:
        self.journal.save_missing_morning_confirmation(trade_date, market_state)
        return self.journal.confirmation(trade_date)


def execution_directive(decision: dict | None) -> dict[str, Any]:
    entity = decision or {}
    outcome = str(entity.get("outcome", "MISSING"))
    return {
        "decision_id": entity.get("decision_id"),
        "outcome": outcome,
        "execute_buy": outcome == "BUY",
        "reason_codes": list(entity.get("reason_codes", [])),
    }
