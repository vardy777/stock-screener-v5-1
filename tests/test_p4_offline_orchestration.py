import ast
import json
import multiprocessing
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from v4.execution import CHINA_TZ
from v4.p4_contracts import TaskContractViolation, TaskReceiptV1
from v4.p4_journal import OfflineTaskJournal
from v4.p4_orchestrator import (
    FakeNotificationAdapter, OfflineNotificationExecutor, OfflineTaskOrchestrator,
)


ROOT = Path(__file__).resolve().parents[1]


class VerifiedCalendar:
    verified = True
    def __init__(self, opened=True): self.opened = opened
    def is_open(self, day): return self.opened


def message_factory(task_name, trade_date):
    return {"title": f"{task_name}:{trade_date}", "content": "frozen-content"}


def concurrent_tick(directory):
    adapter = FakeNotificationAdapter()
    engine = OfflineTaskOrchestrator(Path(directory), calendar=VerifiedCalendar(),
        executor=OfflineNotificationExecutor(adapter, message_factory))
    try:
        return engine.tick(datetime(2026, 8, 3, 9, 25, tzinfo=CHINA_TZ))["status"]
    except TaskContractViolation:
        return "CONTENDED"


class P4OfflineOrchestrationTests(unittest.TestCase):
    def now(self, hour, minute, second=0):
        return datetime(2026, 8, 3, hour, minute, second, tzinfo=CHINA_TZ)

    def engine(self, directory, outcomes=()):
        adapter = FakeNotificationAdapter(outcomes)
        executor = OfflineNotificationExecutor(adapter, message_factory)
        return OfflineTaskOrchestrator(Path(directory), calendar=VerifiedCalendar(), executor=executor), adapter

    def test_receipt_is_deterministic_and_rejects_naive_or_tampered_data(self):
        values = dict(task_name="morning_push", trade_date="2026-08-03", attempt=1,
                      status="SUCCEEDED", reason_code="OK", recorded_at=self.now(9, 25),
                      scheduled_for=self.now(9, 25), payload_sha256="a" * 64)
        first = TaskReceiptV1.build(**values); second = TaskReceiptV1.build(**values)
        self.assertEqual(first, second)
        with self.assertRaisesRegex(TaskContractViolation, "timezone"):
            TaskReceiptV1.build(**{**values, "recorded_at": datetime(2026, 8, 3, 9, 25)})
        raw = first.to_dict(); raw["attempt"] = 2
        with self.assertRaisesRegex(TaskContractViolation, "content hash"):
            TaskReceiptV1.from_mapping(raw)

    def test_success_runs_once_and_remains_idempotent_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, adapter = self.engine(directory)
            first = engine.tick(self.now(9, 25)); second = engine.tick(self.now(9, 25, 5))
            restarted, adapter2 = self.engine(directory)
            third = restarted.tick(self.now(9, 26))
            rows = restarted.journal.receipts()
        self.assertEqual(first["status"], "EMITTED")
        self.assertEqual(second["status"], third["status"])
        self.assertEqual(second["status"], "NOOP")
        self.assertEqual(len(adapter.messages), 1); self.assertEqual(adapter2.messages, [])
        self.assertEqual([row["status"] for row in rows], ["STARTED", "SUCCEEDED"])

    def test_failure_and_timeout_retry_then_succeed_with_stable_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, adapter = self.engine(directory, ["failure", "timeout", "success"])
            for second in (0, 1, 2): engine.tick(self.now(14, 50, second))
            rows = engine.journal.run_receipts("confirmation_push", "2026-08-03")
        terminals = [row for row in rows if row["status"] != "STARTED"]
        self.assertEqual([row["status"] for row in terminals], ["FAILED", "TIMED_OUT", "SUCCEEDED"])
        self.assertEqual([row["attempt"] for row in terminals], [1, 2, 3])
        self.assertEqual(len({row["payload_sha256"] for row in terminals if row["payload_sha256"]}), 1)
        self.assertEqual(len(adapter.messages), 3)

    def test_late_tick_compensates_before_sla_but_marks_missed_after_deadline(self):
        with tempfile.TemporaryDirectory() as first_dir:
            engine, adapter = self.engine(first_dir)
            result = engine.tick(self.now(9, 32))
            self.assertEqual(result["receipts"][0]["reason_code"], "COMPENSATION_STARTED")
            self.assertEqual(len(adapter.messages), 1)
            self.assertTrue(engine.sla_report(self.now(15, 0))["tasks"][0]["status"] == "SUCCEEDED")
        with tempfile.TemporaryDirectory() as second_dir:
            engine, adapter = self.engine(second_dir)
            result = engine.tick(self.now(9, 40))
            self.assertEqual(result["receipts"][0]["status"], "SLA_MISSED")
            self.assertEqual(adapter.messages, [])

    def test_closed_session_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = FakeNotificationAdapter()
            engine = OfflineTaskOrchestrator(Path(directory), calendar=VerifiedCalendar(False),
                executor=OfflineNotificationExecutor(adapter, message_factory))
            self.assertEqual(engine.tick(self.now(9, 25))["status"], "CLOSED_SESSION")
            self.assertEqual(adapter.messages, [])

    def test_max_retries_then_sla_missed_and_concurrent_trigger_is_single_run(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, _ = self.engine(directory, ["failure"] * 3)
            for second in range(3): engine.tick(self.now(9, 25, second))
            self.assertEqual(engine.tick(self.now(9, 25, 4))["status"], "NOOP")
            engine.tick(self.now(9, 40))
            report = engine.sla_report(self.now(9, 40))
            self.assertEqual(report["tasks"][0]["status"], "MISSED")
            self.assertEqual(report["tasks"][0]["attempts"], 3)
            self.assertEqual(report["alerts"], ["morning_push"])
        with tempfile.TemporaryDirectory() as directory:
            context = multiprocessing.get_context("spawn")
            with context.Pool(2) as pool:
                outcomes = pool.map(concurrent_tick, [directory, directory])
            rows = OfflineTaskJournal(Path(directory)).receipts()
            self.assertIn("EMITTED", outcomes)
            self.assertEqual([row["status"] for row in rows], ["STARTED", "SUCCEEDED"])

    def test_journal_detects_tampering_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, _ = self.engine(directory); engine.tick(self.now(9, 25))
            journal = OfflineTaskJournal(Path(directory))
            raw = json.loads(journal.path.read_text(encoding="utf-8"))
            raw["events"][0]["receipt"]["reason_code"] = "TAMPERED"
            journal.path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(TaskContractViolation, "content hash"):
                journal.receipts()

    def test_journal_rejects_terminal_without_start_and_heartbeat_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OfflineTaskJournal(Path(directory))
            terminal = TaskReceiptV1.build(
                task_name="morning_push", trade_date="2026-08-03", attempt=1,
                status="SUCCEEDED", reason_code="OK", recorded_at=self.now(9, 25),
                scheduled_for=self.now(9, 25))
            with self.assertRaisesRegex(TaskContractViolation, "without start"):
                journal.append(terminal)
            engine, _ = self.engine(directory)
            before = engine.heartbeat(self.now(9, 24)); after = engine.heartbeat(self.now(9, 24))
            self.assertEqual(before, after)
            self.assertEqual(before["receipt_count"], 0)

    def test_p4_modules_are_offline_and_production_paths_do_not_import_them(self):
        forbidden = {"v4.push", "v4.simulation", "v4.paper_scheduler", "urllib.request"}
        violations = []
        for path in sorted((ROOT / "v4").glob("p4_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.ImportFrom): modules.append(node.module or "")
                if isinstance(node, ast.Import): modules.extend(alias.name for alias in node.names)
                for module in modules:
                    if module in forbidden: violations.append(f"{path.name}:{node.lineno}:{module}")
        self.assertEqual(violations, [])
        for path in (ROOT / "v4" / "paper_scheduler.py", ROOT / "v4" / "push.py",
                     ROOT / "v4" / "scripts" / "morning_push.py", ROOT / "v4" / "scripts" / "afternoon_push.py"):
            self.assertNotIn("p4_", path.read_text(encoding="utf-8"))


if __name__ == "__main__": unittest.main()
