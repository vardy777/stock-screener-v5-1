"""Deterministic P2 contract replay; never presented as historical evidence."""

from __future__ import annotations

from typing import Any, Mapping
import hashlib

from .decision_contracts import ConfirmationDecisionV1, MorningPoolV1


def replay_contract_case(case: Mapping[str, Any]) -> dict:
    trade_date = str(case["trade_date"])
    timestamp = case["timestamp"]
    market = dict(case.get("market_state", {}))
    # Legacy synthetic golden cases predate snapshot persistence. Give them an
    # explicit synthetic lineage; this path never qualifies as evidence.
    seed = hashlib.sha256(trade_date.encode("utf-8")).hexdigest()
    market.setdefault("snapshot_id", "ms1-" + seed)
    market.setdefault("market_state_id", "mstate1-" + seed)
    morning_rows = case.get("morning_candidates")
    if morning_rows is None:
        decision = ConfirmationDecisionV1.blocked_without_morning(
            trade_date, timestamp, market
        )
        pool_id = "missing"
    else:
        morning = MorningPoolV1.build(
            trade_date, timestamp, morning_rows, market
        )
        pool_id = morning.pool_id
        confirmation_rows = [dict(item) for item in case.get("confirmation_candidates", [])]
        for item in confirmation_rows:
            item.setdefault("v4_paper_policy_version", "synthetic-golden-policy-v1")
        decision = ConfirmationDecisionV1.build(morning, timestamp, confirmation_rows, market)
    payload = decision.to_dict()
    return {
        "replay_kind": "synthetic_contract_golden",
        "trade_date": trade_date,
        "morning_pool_id": pool_id,
        "decision_id": decision.decision_id,
        "outcome": decision.outcome,
        "reason_codes": list(decision.reason_codes),
        "push_outcome": payload["outcome"],
        "dashboard_outcome": payload["outcome"],
        "execution_outcome": payload["outcome"],
    }
