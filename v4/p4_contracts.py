"""Immutable P4 task and receipt contracts for offline orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time
import hashlib
import json


TASK_SPEC_VERSION = "task-spec-v1"
TASK_RECEIPT_VERSION = "task-receipt-v1"


class TaskContractViolation(ValueError):
    pass


def _aware(value, field):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise TaskContractViolation(f"{field}: invalid datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TaskContractViolation(f"{field}: timezone required")
    return parsed.isoformat(timespec="seconds")


def _identity(prefix, payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return prefix + "-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class TaskSpecV1:
    task_name: str
    scheduled_time: str
    window_end: str
    sla_deadline: str
    max_attempts: int = 3
    compensation_allowed: bool = True
    historical_compensation_allowed: bool = False
    schema_version: str = TASK_SPEC_VERSION

    @classmethod
    def build(cls, *, task_name, scheduled_time, window_end, sla_deadline,
              max_attempts=3, compensation_allowed=True, historical_compensation_allowed=False):
        if task_name not in {"morning_push", "confirmation_push", "paper_sell", "paper_buy"}:
            raise TaskContractViolation("task spec: unknown task")
        try:
            start = time.fromisoformat(str(scheduled_time))
            end = time.fromisoformat(str(window_end))
            deadline = time.fromisoformat(str(sla_deadline))
        except ValueError as exc:
            raise TaskContractViolation("task spec: invalid time") from exc
        if not start < end <= deadline:
            raise TaskContractViolation("task spec: time order invalid")
        attempts = int(max_attempts)
        if attempts < 1 or attempts > 5:
            raise TaskContractViolation("task spec: attempts out of range")
        return cls(task_name, start.isoformat(), end.isoformat(), deadline.isoformat(),
                   attempts, bool(compensation_allowed), bool(historical_compensation_allowed))

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class TaskReceiptV1:
    receipt_id: str
    run_id: str
    task_name: str
    trade_date: str
    attempt: int
    status: str
    reason_code: str
    recorded_at: str
    scheduled_for: str
    payload_sha256: str = ""
    schema_version: str = TASK_RECEIPT_VERSION

    @classmethod
    def build(cls, *, task_name, trade_date, attempt, status, reason_code,
              recorded_at, scheduled_for, payload_sha256=""):
        if task_name not in {"morning_push", "confirmation_push", "paper_sell", "paper_buy"}:
            raise TaskContractViolation("receipt: unknown task")
        if status not in {"STARTED", "SUCCEEDED", "FAILED", "TIMED_OUT", "SLA_MISSED"}:
            raise TaskContractViolation("receipt: invalid status")
        day = date.fromisoformat(str(trade_date)).isoformat()
        attempt = int(attempt)
        if attempt < 0 or (status != "SLA_MISSED" and attempt < 1):
            raise TaskContractViolation("receipt: invalid attempt")
        scheduled = _aware(scheduled_for, "scheduled_for")
        recorded = _aware(recorded_at, "recorded_at")
        if datetime.fromisoformat(scheduled).date().isoformat() != day:
            raise TaskContractViolation("receipt: scheduled date mismatch")
        run_id = _identity("trun", {"task_name": task_name, "trade_date": day})
        payload = {"schema_version": TASK_RECEIPT_VERSION, "run_id": run_id,
                   "task_name": task_name, "trade_date": day, "attempt": attempt,
                   "status": status, "reason_code": str(reason_code),
                   "recorded_at": recorded, "scheduled_for": scheduled,
                   "payload_sha256": str(payload_sha256)}
        return cls(receipt_id=_identity("trec", payload), **{k: v for k, v in payload.items() if k != "schema_version"})

    def to_dict(self):
        return asdict(self)

    def verify(self):
        if self.schema_version != TASK_RECEIPT_VERSION:
            raise TaskContractViolation("receipt: schema mismatch")
        payload = self.to_dict(); payload.pop("receipt_id")
        if self.receipt_id != _identity("trec", payload):
            raise TaskContractViolation("receipt: content hash mismatch")
        return self

    @classmethod
    def from_mapping(cls, value):
        try:
            return cls(**dict(value)).verify()
        except TypeError as exc:
            raise TaskContractViolation("receipt: invalid fields") from exc
