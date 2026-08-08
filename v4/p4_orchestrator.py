"""Frozen-clock P4 orchestration. No production entrypoint imports this module."""

from __future__ import annotations

from datetime import datetime, time
import hashlib
from pathlib import Path

from .p4_contracts import TaskContractViolation, TaskReceiptV1, TaskSpecV1
from .p4_journal import OfflineTaskJournal


DEFAULT_OFFLINE_SPECS = (
    TaskSpecV1.build(task_name="morning_push", scheduled_time="09:25:00",
                     window_end="09:29:59", sla_deadline="09:35:00"),
    TaskSpecV1.build(task_name="confirmation_push", scheduled_time="14:50:00",
                     window_end="14:51:59", sla_deadline="14:55:00"),
)


class OfflineTaskOrchestrator:
    def __init__(self, directory: Path, *, calendar, executor, specs=DEFAULT_OFFLINE_SPECS):
        if getattr(calendar, "verified", False) is not True:
            raise TaskContractViolation("orchestrator: verified calendar required")
        self.calendar = calendar
        self.executor = executor
        self.specs = tuple(specs)
        self.journal = OfflineTaskJournal(Path(directory))

    @staticmethod
    def _scheduled(now, spec):
        return datetime.combine(now.date(), time.fromisoformat(spec.scheduled_time), now.tzinfo)

    def _append(self, spec, now, attempt, status, reason, payload=""):
        receipt = TaskReceiptV1.build(
            task_name=spec.task_name, trade_date=now.date(), attempt=attempt,
            status=status, reason_code=reason, recorded_at=now,
            scheduled_for=self._scheduled(now, spec), payload_sha256=payload,
        )
        self.journal.append(receipt)
        return receipt.to_dict()

    def tick(self, now: datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise TaskContractViolation("orchestrator: timezone required")
        if self.calendar.is_open(now.date()) is not True:
            return {"status": "CLOSED_SESSION", "receipts": []}
        emitted = []
        for spec in self.specs:
            clock = now.timetz().replace(tzinfo=None)
            start, end, deadline = map(time.fromisoformat, (spec.scheduled_time, spec.window_end, spec.sla_deadline))
            history = self.journal.run_receipts(spec.task_name, now.date().isoformat())
            if any(row["status"] == "SUCCEEDED" for row in history):
                continue
            terminal_attempts = [row for row in history if row["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT"}]
            attempt = len(terminal_attempts) + 1
            if clock > deadline:
                if not any(row["status"] == "SLA_MISSED" for row in history):
                    emitted.append(self._append(spec, now, 0, "SLA_MISSED", "SLA_DEADLINE_EXCEEDED"))
                continue
            in_window = start <= clock <= end
            compensating = end < clock <= deadline and spec.compensation_allowed
            if not in_window and not compensating:
                continue
            if attempt > spec.max_attempts:
                continue
            emitted.append(self._append(
                spec, now, attempt, "STARTED",
                "COMPENSATION_STARTED" if compensating else "SCHEDULED_STARTED"))
            try:
                result = self.executor(spec.task_name, now.date().isoformat(), attempt)
                status = str(result.get("status", "FAILED")).upper()
                if status not in {"SUCCEEDED", "FAILED", "TIMED_OUT"}:
                    status = "FAILED"
                reason = str(result.get("reason_code", status))
                payload = str(result.get("payload_sha256", ""))
            except TimeoutError:
                status, reason, payload = "TIMED_OUT", "TRANSPORT_TIMEOUT", ""
            except Exception:
                status, reason, payload = "FAILED", "EXECUTOR_EXCEPTION", ""
            emitted.append(self._append(spec, now, attempt, status, reason, payload))
        return {"status": "EMITTED" if emitted else "NOOP", "receipts": emitted}

    def sla_report(self, now: datetime):
        rows = self.journal.receipts()
        result = []
        for spec in self.specs:
            history = [row for row in rows if row["task_name"] == spec.task_name and row["trade_date"] == now.date().isoformat()]
            status = "SUCCEEDED" if any(row["status"] == "SUCCEEDED" for row in history) else (
                "MISSED" if any(row["status"] == "SLA_MISSED" for row in history) else "PENDING")
            result.append({"task_name": spec.task_name, "status": status,
                           "attempts": sum(row["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT"} for row in history)})
        return {"schema_version": "task-sla-report-v1", "trade_date": now.date().isoformat(),
                "tasks": result, "alerts": [row["task_name"] for row in result if row["status"] == "MISSED"],
                "passed": all(row["status"] == "SUCCEEDED" for row in result)}

    def heartbeat(self, now: datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise TaskContractViolation("heartbeat: timezone required")
        rows = self.journal.receipts()
        return {"schema_version": "offline-orchestrator-heartbeat-v1",
                "observed_at": now.isoformat(timespec="seconds"), "status": "ALIVE",
                "offline_only": True, "receipt_count": len(rows),
                "last_receipt_id": rows[-1]["receipt_id"] if rows else ""}


class OfflineNotificationExecutor:
    def __init__(self, adapter, message_factory):
        self.adapter = adapter
        self.message_factory = message_factory

    def __call__(self, task_name, trade_date, attempt):
        message = self.message_factory(task_name, trade_date)
        payload = hashlib.sha256(
            (message["title"] + "\n" + message["content"]).encode("utf-8")
        ).hexdigest()
        outcome = self.adapter.send(
            task_name=task_name, trade_date=trade_date, attempt=attempt,
            title=message["title"], content=message["content"])
        if outcome == "timeout":
            raise TimeoutError("fake timeout")
        return {"status": "SUCCEEDED" if outcome == "success" else "FAILED",
                "reason_code": "TRANSPORT_ACCEPTED" if outcome == "success" else "TRANSPORT_REJECTED",
                "payload_sha256": payload}


class FakeNotificationAdapter:
    """Deterministic offline adapter; never accesses network or PushPlus tokens."""
    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.messages = []

    def send(self, **message):
        self.messages.append(dict(message))
        return self.outcomes.pop(0) if self.outcomes else "success"
