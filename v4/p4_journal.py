"""Append-only P4 receipt journal, isolated from production paths."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .offline_storage import atomic_json_write
from .offline_storage import exclusive_file_lock as _exclusive_file_lock
from .p4_contracts import TaskContractViolation, TaskReceiptV1


class OfflineTaskJournal:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.path = self.directory / "task_receipts.json"
        self.lock_path = self.directory / ".task_receipts.lock"

    @staticmethod
    def _event_id(sequence, previous, receipt_id):
        raw = json.dumps({"sequence": sequence, "previous": previous,
                          "receipt_id": receipt_id}, sort_keys=True, separators=(",", ":"))
        return "tev-" + hashlib.sha256(raw.encode()).hexdigest()[:24]

    def receipts(self):
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TaskContractViolation("task journal: invalid JSON") from exc
        events = payload.get("events", [])
        if payload.get("schema_version") != "offline-task-journal-v1" or payload.get("event_count") != len(events):
            raise TaskContractViolation("task journal: schema or count mismatch")
        previous = "genesis"; result = []
        for sequence, event in enumerate(events, 1):
            receipt = TaskReceiptV1.from_mapping(event.get("receipt", {}))
            expected = self._event_id(sequence, previous, receipt.receipt_id)
            if event.get("sequence") != sequence or event.get("previous") != previous or event.get("event_id") != expected:
                raise TaskContractViolation("task journal: event chain mismatch")
            previous = expected; result.append(receipt.to_dict())
        if payload.get("head_event_id") != previous:
            raise TaskContractViolation("task journal: head mismatch")
        return result

    def append(self, receipt: TaskReceiptV1):
        receipt.verify()
        with _exclusive_file_lock(self.lock_path, error_type=TaskContractViolation):
            rows = self.receipts()
            if any(row["receipt_id"] == receipt.receipt_id for row in rows):
                return False
            run = [row for row in rows if row["run_id"] == receipt.run_id]
            succeeded = any(row["status"] == "SUCCEEDED" for row in run)
            if succeeded:
                raise TaskContractViolation("task journal: run already succeeded")
            same_attempt = [row for row in run if row["attempt"] == receipt.attempt]
            if receipt.status == "STARTED":
                if same_attempt:
                    raise TaskContractViolation("task journal: duplicate attempt")
            elif receipt.status in {"SUCCEEDED", "FAILED", "TIMED_OUT"}:
                if not any(row["status"] == "STARTED" for row in same_attempt):
                    raise TaskContractViolation("task journal: terminal without start")
                if any(row["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT"} for row in same_attempt):
                    raise TaskContractViolation("task journal: duplicate terminal")
            elif receipt.status == "OUTCOME_UNKNOWN":
                if not any(row["status"] == "STARTED" for row in same_attempt):
                    raise TaskContractViolation("task journal: unknown without start")
                if any(row["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT", "OUTCOME_UNKNOWN"} for row in same_attempt):
                    raise TaskContractViolation("task journal: duplicate unknown")
            elif receipt.status == "SLA_MISSED" and any(row["status"] == "SLA_MISSED" for row in run):
                raise TaskContractViolation("task journal: duplicate SLA event")
            previous = "genesis" if not self.path.exists() else json.loads(self.path.read_text(encoding="utf-8"))["head_event_id"]
            sequence = len(rows) + 1
            event_id = self._event_id(sequence, previous, receipt.receipt_id)
            events = [] if not self.path.exists() else json.loads(self.path.read_text(encoding="utf-8"))["events"]
            events.append({"sequence": sequence, "previous": previous, "event_id": event_id,
                           "receipt": receipt.to_dict()})
            atomic_json_write(self.path, {"schema_version": "offline-task-journal-v1",
                              "event_count": sequence, "head_event_id": event_id, "events": events})
            return True

    def run_receipts(self, task_name, trade_date):
        return [row for row in self.receipts() if row["task_name"] == task_name and row["trade_date"] == trade_date]
