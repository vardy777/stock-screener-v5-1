"""Deterministic notification projections from frozen P2 entities."""

from __future__ import annotations

import hashlib
import json

from .decision_contracts import ConfirmationDecisionV1, MorningPoolV1
from .p4_contracts import TaskContractViolation


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FrozenNotificationProjector:
    @staticmethod
    def morning(entity: MorningPoolV1):
        if not isinstance(entity, MorningPoolV1):
            raise TaskContractViolation("notification: frozen MorningPoolV1 required")
        lineage = dict(entity.lineage)
        payload = {"schema_version": "frozen-notification-payload-v1", "task_name": "morning_push",
                   "trade_date": entity.trade_date, "entity_id": entity.pool_id,
                   "entity_schema_version": entity.schema_version,
                   "input_snapshot_id": lineage.get("input_snapshot_id", ""),
                   "market_state_id": lineage.get("market_state_id", ""),
                   "ranking_version": lineage.get("ranking_version", ""),
                   "candidate_codes": list(entity.candidate_codes)}
        return {**payload, "payload_sha256": _hash(payload)}

    @staticmethod
    def confirmation(entity: ConfirmationDecisionV1, morning: MorningPoolV1):
        if not isinstance(entity, ConfirmationDecisionV1) or not isinstance(morning, MorningPoolV1):
            raise TaskContractViolation("notification: frozen decision and morning pool required")
        if entity.morning_pool_id != morning.pool_id or entity.trade_date != morning.trade_date:
            raise TaskContractViolation("notification: morning lineage mismatch")
        if not set(entity.candidate_codes).issubset(morning.candidate_codes):
            raise TaskContractViolation("notification: candidate subset violation")
        lineage = dict(entity.lineage)
        payload = {"schema_version": "frozen-notification-payload-v1", "task_name": "confirmation_push",
                   "trade_date": entity.trade_date, "entity_id": entity.decision_id,
                   "morning_pool_id": entity.morning_pool_id, "entity_schema_version": entity.schema_version,
                   "outcome": entity.outcome, "reason_codes": list(entity.reason_codes),
                   "input_snapshot_id": lineage.get("input_snapshot_id", ""),
                   "market_state_id": lineage.get("market_state_id", ""),
                   "ranking_version": lineage.get("ranking_version", ""),
                   "candidate_codes": list(entity.candidate_codes)}
        return {**payload, "payload_sha256": _hash(payload)}


class BoundNotificationExecutor:
    """Bind frozen entity payload -> request ID -> transport result -> receipt fields."""
    def __init__(self, adapter, payload_loader):
        self.adapter = adapter; self.payload_loader = payload_loader

    def __call__(self, task_name, trade_date, attempt):
        payload = dict(self.payload_loader(task_name, trade_date))
        payload_hash = payload.pop("payload_sha256", "")
        if payload_hash != _hash(payload):
            raise TaskContractViolation("notification: payload hash mismatch")
        request_id = "nreq-" + _hash({"task_name": task_name, "trade_date": trade_date,
                                      "payload_sha256": payload_hash})[:24]
        outcome = self.adapter.send(task_name=task_name, trade_date=trade_date,
                                    attempt=attempt, request_id=request_id, payload=payload)
        return {"status": "SUCCEEDED" if outcome == "success" else "FAILED",
                "reason_code": "TRANSPORT_ACCEPTED" if outcome == "success" else "TRANSPORT_REJECTED",
                "payload_sha256": payload_hash, "transport_request_id": request_id}
