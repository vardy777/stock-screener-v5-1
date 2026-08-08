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
    def _scheduled(now, spec, trade_date=None):
        day = now.date() if trade_date is None else datetime.fromisoformat(str(trade_date)).date()
        return datetime.combine(day, time.fromisoformat(spec.scheduled_time), now.tzinfo)

    def _append(self, spec, now, attempt, status, reason, payload="", trade_date=None, transport_request_id=""):
        day = now.date().isoformat() if trade_date is None else str(trade_date)
        receipt = TaskReceiptV1.build(
            task_name=spec.task_name, trade_date=day, attempt=attempt,
            status=status, reason_code=reason, recorded_at=now,
            scheduled_for=self._scheduled(now, spec, day), payload_sha256=payload,
            transport_request_id=transport_request_id,
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
            if not spec.enabled:
                continue
            clock = now.timetz().replace(tzinfo=None)
            start, end, deadline = map(time.fromisoformat, (spec.scheduled_time, spec.window_end, spec.sla_deadline))
            history = self.journal.run_receipts(spec.task_name, now.date().isoformat())
            if any(row["status"] == "SUCCEEDED" for row in history):
                continue
            unresolved = [row for row in history if row["status"] == "OUTCOME_UNKNOWN" and not any(
                later["attempt"] == row["attempt"] and later["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT"} for later in history)]
            if unresolved:
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
            dependency_blocked = any(not any(
                row["task_name"] == dependency and row["trade_date"] == now.date().isoformat() and row["status"] == "SUCCEEDED"
                for row in self.journal.receipts()) for dependency in spec.dependencies)
            if dependency_blocked:
                continue
            try:
                emitted.append(self._append(spec, now, attempt, "STARTED",
                    "COMPENSATION_STARTED" if compensating else "SCHEDULED_STARTED"))
            except TaskContractViolation as exc:
                if "duplicate attempt" in str(exc) or "already succeeded" in str(exc):
                    continue
                raise
            try:
                result = self.executor(spec.task_name, now.date().isoformat(), attempt)
                status = str(result.get("status", "FAILED")).upper()
                if status not in {"SUCCEEDED", "FAILED", "TIMED_OUT"}:
                    status = "FAILED"
                reason = str(result.get("reason_code", status))
                payload = str(result.get("payload_sha256", ""))
                transport = str(result.get("transport_request_id", ""))
            except TimeoutError:
                status, reason, payload, transport = "TIMED_OUT", "TRANSPORT_TIMEOUT", "", ""
            except Exception:
                status, reason, payload, transport = "FAILED", "EXECUTOR_EXCEPTION", "", ""
            emitted.append(self._append(spec, now, attempt, status, reason, payload, transport_request_id=transport))
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

    def scan_sessions(self, session_dates, *, observed_at: datetime):
        """Audit past sessions; stale pushes are never replayed."""
        emitted = []
        for raw_day in session_dates:
            day = datetime.fromisoformat(str(raw_day)).date()
            if day >= observed_at.date() or self.calendar.is_open(day) is not True:
                continue
            for spec in self.specs:
                history = self.journal.run_receipts(spec.task_name, day.isoformat())
                if any(row["status"] in {"SUCCEEDED", "SLA_MISSED"} for row in history):
                    continue
                if spec.historical_compensation_allowed:
                    attempt = 1 + sum(row["status"] in {"FAILED", "TIMED_OUT"} for row in history)
                    emitted.append(self._append(spec, observed_at, attempt, "STARTED", "HISTORICAL_COMPENSATION_STARTED", trade_date=day.isoformat()))
                    try:
                        result = self.executor(spec.task_name, day.isoformat(), attempt)
                        status = str(result.get("status", "FAILED")).upper()
                        reason = str(result.get("reason_code", status)); payload = str(result.get("payload_sha256", ""))
                    except Exception:
                        status, reason, payload = "FAILED", "EXECUTOR_EXCEPTION", ""
                    emitted.append(self._append(spec, observed_at, attempt, status, reason, payload, day.isoformat()))
                else:
                    emitted.append(self._append(spec, observed_at, 0, "SLA_MISSED", "HISTORICAL_SLA_MISSED_NO_STALE_REPLAY", trade_date=day.isoformat()))
        return {"schema_version": "multi-session-recovery-v1", "receipts": emitted}

    def recovery_report(self):
        rows = self.journal.receipts(); inflight = []
        for row in rows:
            if row["status"] != "STARTED": continue
            if not any(item["run_id"] == row["run_id"] and item["attempt"] == row["attempt"] and item["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT", "OUTCOME_UNKNOWN"} for item in rows):
                inflight.append(row)
        return {"schema_version": "task-recovery-report-v1", "status": "RECOVERY_REQUIRED" if inflight else "CLEAN", "interrupted_attempts": inflight}

    def recover_interrupted(self, *, observed_at: datetime):
        repaired = []
        for row in self.recovery_report()["interrupted_attempts"]:
            spec = next(item for item in self.specs if item.task_name == row["task_name"])
            repaired.append(self._append(spec, observed_at, row["attempt"], "OUTCOME_UNKNOWN", "PROCESS_INTERRUPTED_OUTCOME_UNKNOWN", trade_date=row["trade_date"]))
        return {"repaired": repaired, "recovery": self.recovery_report()}

    def resolve_unknown(self, *, task_name, trade_date, attempt, observed_at, delivered: bool):
        spec = next(item for item in self.specs if item.task_name == task_name)
        return self._append(spec, observed_at, attempt, "SUCCEEDED" if delivered else "FAILED",
                            "EXTERNAL_RESULT_CONFIRMED" if delivered else "EXTERNAL_RESULT_NOT_DELIVERED",
                            trade_date=trade_date)

    def alert_report(self, now: datetime, *, last_heartbeat_at: datetime, heartbeat_limit_seconds=120):
        if last_heartbeat_at.tzinfo is None or last_heartbeat_at.utcoffset() is None:
            raise TaskContractViolation("alert: heartbeat timezone required")
        age = (now - last_heartbeat_at).total_seconds()
        rows = self.journal.receipts()
        alerts = []
        if age > heartbeat_limit_seconds:
            alerts.append({"severity": "CRITICAL", "reason_code": "HEARTBEAT_STALE", "age_seconds": age})
        for row in rows:
            if row["status"] == "SLA_MISSED": alerts.append({"severity": "ERROR", "reason_code": "TASK_SLA_MISSED", "run_id": row["run_id"]})
            elif row["status"] in {"FAILED", "TIMED_OUT"}: alerts.append({"severity": "WARNING", "reason_code": row["reason_code"], "run_id": row["run_id"]})
        rank = {"WARNING": 1, "ERROR": 2, "CRITICAL": 3}
        highest = max((item["severity"] for item in alerts), key=lambda value: rank[value], default="NONE")
        return {"schema_version": "task-alert-report-v1", "highest_severity": highest, "alerts": alerts}

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
