"""Content-addressed last-mile output contracts for every P4 task.

This module is deliberately transport-neutral: an exit code is never accepted as
business success unless the task also records the required immutable entity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json

from .p4_contracts import TASK_NAMES, TaskContractViolation


TASK_OUTPUT_VERSION = "task-output-v1"
OUTPUT_KINDS = {
    "morning_decision": "MorningPoolV1",
    "morning_push": "NotificationReceiptV1",
    "paper_sell": "PaperExecutionResultV1",
    "feature_freeze": "FeatureContextV1",
    "confirmation_decision": "ConfirmationDecisionV1",
    "confirmation_push": "NotificationReceiptV1",
    "paper_buy": "PaperExecutionResultV1",
    "health_check": "HealthReportV1",
    "maintenance": "MaintenanceReportV1",
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _aware(value, field):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise TaskContractViolation(f"task output: invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TaskContractViolation(f"task output: {field} timezone required")
    return parsed.isoformat(timespec="seconds")


@dataclass(frozen=True)
class TaskOutputV1:
    output_id: str
    task_name: str
    trade_date: str
    status: str
    reason_code: str
    recorded_at: str
    entity_kind: str
    entity_id: str
    entity_sha256: str
    input_ids: tuple[str, ...]
    schema_version: str = TASK_OUTPUT_VERSION

    @classmethod
    def build(cls, *, task_name, trade_date, status, reason_code, recorded_at,
              entity_kind="", entity_id="", entity_payload=None, input_ids=()):
        if task_name not in TASK_NAMES:
            raise TaskContractViolation("task output: unknown task")
        if status not in {"SUCCEEDED", "BLOCKED", "FAILED", "OUTCOME_UNKNOWN"}:
            raise TaskContractViolation("task output: invalid status")
        day = date.fromisoformat(str(trade_date)).isoformat()
        timestamp = _aware(recorded_at, "recorded_at")
        inputs = tuple(str(item) for item in input_ids)
        if status == "SUCCEEDED":
            expected = OUTPUT_KINDS[task_name]
            if entity_kind != expected or not str(entity_id):
                raise TaskContractViolation(f"task output: {expected} required")
            if entity_payload is None:
                raise TaskContractViolation("task output: entity payload required")
        digest = _hash(entity_payload) if entity_payload is not None else ""
        body = {"schema_version": TASK_OUTPUT_VERSION, "task_name": task_name,
                "trade_date": day, "status": status, "reason_code": str(reason_code),
                "recorded_at": timestamp, "entity_kind": str(entity_kind),
                "entity_id": str(entity_id), "entity_sha256": digest,
                "input_ids": list(inputs)}
        output_id = "tout-" + _hash(body)[:24]
        return cls(output_id, task_name, day, status, str(reason_code), timestamp,
                   str(entity_kind), str(entity_id), digest, inputs)

    def to_dict(self):
        value = asdict(self)
        value["input_ids"] = list(self.input_ids)
        return value

    def verify(self, entity_payload=None):
        if self.schema_version != TASK_OUTPUT_VERSION:
            raise TaskContractViolation("task output: schema mismatch")
        body = self.to_dict(); body.pop("output_id")
        expected = "tout-" + _hash(body)[:24]
        if expected != self.output_id:
            raise TaskContractViolation("task output: content hash mismatch")
        if self.status == "SUCCEEDED":
            if self.entity_kind != OUTPUT_KINDS.get(self.task_name) or not self.entity_id:
                raise TaskContractViolation("task output: required entity mismatch")
            if entity_payload is not None and _hash(entity_payload) != self.entity_sha256:
                raise TaskContractViolation("task output: entity hash mismatch")
        return self

    @classmethod
    def from_mapping(cls, value):
        raw = dict(value); raw["input_ids"] = tuple(raw.get("input_ids", ()))
        try:
            return cls(**raw).verify()
        except TypeError as exc:
            raise TaskContractViolation("task output: invalid fields") from exc


def audit_output_chain(outputs):
    """Validate one immutable output per task and dependency ID continuity."""
    rows = [TaskOutputV1.from_mapping(x) if not isinstance(x, TaskOutputV1) else x.verify()
            for x in outputs]
    by_name = {}
    issues = []
    for row in rows:
        if row.task_name in by_name:
            issues.append(f"DUPLICATE_TASK_OUTPUT:{row.task_name}")
        by_name[row.task_name] = row
    dependencies = {
        "morning_push": ("morning_decision",),
        "confirmation_decision": ("morning_decision", "feature_freeze"),
        "confirmation_push": ("confirmation_decision",),
        "paper_buy": ("confirmation_decision",),
        "health_check": ("confirmation_decision",),
        "maintenance": ("health_check",),
    }
    for name, deps in dependencies.items():
        row = by_name.get(name)
        if not row or row.status != "SUCCEEDED":
            continue
        for dep in deps:
            source = by_name.get(dep)
            if not source or source.entity_id not in row.input_ids:
                issues.append(f"MISSING_INPUT_LINEAGE:{name}:{dep}")
    return {"schema_version": "task-output-audit-v1", "passed": not issues,
            "issues": issues, "outputs": [x.to_dict() for x in rows]}
