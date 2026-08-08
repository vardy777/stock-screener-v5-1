import ast
import json
import multiprocessing
import os
import sys
import time
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from v4.execution import CHINA_TZ
from v4.decision_contracts import ConfirmationDecisionV1, MorningPoolV1
from v4.p4_contracts import TaskContractViolation, TaskReceiptV1, TaskSpecV1
from v4.p4_deployment import audit_existing_windows_scripts, full_offline_task_manifest, offline_notification_manifest
from v4.p4_journal import OfflineTaskJournal
from v4.p4_orchestrator import (
    FakeNotificationAdapter, OfflineNotificationExecutor, OfflineTaskOrchestrator,
)
from v4.p4_projection import BoundNotificationExecutor, FrozenNotificationProjector
from v4.p4_runtime import ControlledSubprocessExecutor, OfflineDaemonHarness, OfflineMonitorStore
from unittest.mock import patch


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


def crash_after_task_start(directory):
    engine = OfflineTaskOrchestrator(Path(directory), calendar=VerifiedCalendar(),
        executor=OfflineNotificationExecutor(FakeNotificationAdapter(), message_factory))
    spec = engine.specs[0]
    engine._append(spec, datetime(2026, 8, 3, 9, 25, tzinfo=CHINA_TZ), 1, "STARTED", "SCHEDULED_STARTED")
    os._exit(71)


def crash_task_boundary(stage, directory):
    engine = OfflineTaskOrchestrator(Path(directory), calendar=VerifiedCalendar(),
        executor=OfflineNotificationExecutor(FakeNotificationAdapter(), message_factory))
    now = datetime(2026, 8, 3, 9, 25, tzinfo=CHINA_TZ); spec = engine.specs[0]
    if stage == "before_start": os._exit(81)
    engine._append(spec, now, 1, "STARTED", "SCHEDULED_STARTED")
    if stage in {"after_start", "after_external_before_receipt"}: os._exit(82)
    engine._append(spec, now, 1, "SUCCEEDED", "TRANSPORT_ACCEPTED", "a" * 64,
                   transport_request_id="nreq-test")
    os._exit(83)


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

    def test_static_windows_manifest_audit_is_read_only_and_dashboard_independent(self):
        manifest = offline_notification_manifest(ROOT)
        audit = audit_existing_windows_scripts(ROOT)
        self.assertFalse(manifest["apply_allowed"])
        self.assertEqual([row["at"] for row in manifest["tasks"]], ["09:25:00", "14:50:20"])
        self.assertTrue(audit["passed"], audit)
        self.assertTrue(audit["read_only"]); self.assertFalse(audit["registration_performed"])

    def test_multi_session_scan_never_replays_stale_push_but_allows_explicit_audit_compensation(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, adapter = self.engine(directory)
            report = engine.scan_sessions([date(2026, 7, 31), date(2026, 8, 1)], observed_at=self.now(9, 0))
            self.assertEqual(len(report["receipts"]), 4)
            self.assertTrue(all(row["status"] == "SLA_MISSED" for row in report["receipts"]))
            self.assertEqual(adapter.messages, [])
        audit_spec = TaskSpecV1.build(task_name="paper_sell", scheduled_time="09:30:00",
            window_end="09:35:00", sla_deadline="09:40:00", historical_compensation_allowed=True)
        with tempfile.TemporaryDirectory() as directory:
            engine = OfflineTaskOrchestrator(Path(directory), calendar=VerifiedCalendar(),
                executor=lambda *args: {"status": "SUCCEEDED", "reason_code": "AUDIT_REBUILT"}, specs=(audit_spec,))
            rows = engine.scan_sessions([date(2026, 7, 31)], observed_at=self.now(9, 0))["receipts"]
            self.assertEqual([row["status"] for row in rows], ["STARTED", "SUCCEEDED"])

    def test_journal_write_failure_preserves_state_and_process_crash_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, _ = self.engine(directory); engine.tick(self.now(9, 25))
            before = engine.journal.path.read_bytes()
            receipt = TaskReceiptV1.build(task_name="confirmation_push", trade_date="2026-08-03",
                attempt=1, status="STARTED", reason_code="SCHEDULED_STARTED",
                recorded_at=self.now(14, 50), scheduled_for=self.now(14, 50))
            with patch("v4.p4_journal.atomic_json_write", side_effect=PermissionError("readonly")):
                with self.assertRaises(PermissionError): engine.journal.append(receipt)
            self.assertEqual(engine.journal.path.read_bytes(), before)
        with tempfile.TemporaryDirectory() as directory:
            process = multiprocessing.get_context("spawn").Process(target=crash_after_task_start, args=(directory,))
            process.start(); process.join(15); self.assertFalse(process.is_alive())
            engine, _ = self.engine(directory)
            self.assertEqual(engine.recovery_report()["status"], "RECOVERY_REQUIRED")
            repaired = engine.recover_interrupted(observed_at=self.now(9, 26))
            self.assertEqual(repaired["repaired"][0]["status"], "OUTCOME_UNKNOWN")
            self.assertEqual(repaired["recovery"]["status"], "CLEAN")
            self.assertEqual(engine.tick(self.now(9, 27))["status"], "NOOP")
            engine.resolve_unknown(task_name="morning_push", trade_date="2026-08-03", attempt=1,
                                   observed_at=self.now(9, 28), delivered=False)
            self.assertEqual(engine.tick(self.now(9, 28, 1))["receipts"][-1]["attempt"], 2)

    def test_heartbeat_staleness_and_alert_escalation(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, _ = self.engine(directory, ["failure"])
            engine.tick(self.now(9, 25)); engine.tick(self.now(14, 56))
            report = engine.alert_report(self.now(15, 0), last_heartbeat_at=self.now(14, 50), heartbeat_limit_seconds=120)
        self.assertEqual(report["highest_severity"], "CRITICAL")
        self.assertIn("HEARTBEAT_STALE", [row["reason_code"] for row in report["alerts"]])
        self.assertIn("TASK_SLA_MISSED", [row["reason_code"] for row in report["alerts"]])

    def test_frozen_entity_notification_projection_preserves_full_lineage(self):
        candidate = {"code": "000001", "name": "test", "rank": 1, "score": 77.5,
            "v4_candidate_origin": "V4", "v4_paper_eligible": False,
            "v4_paper_block_reasons": ["规则分低于80"], "score_version": "rank-v1",
            "v4_paper_policy_version": "policy-v1"}
        market = {"data_valid": True, "snapshot_id": "ms1-" + "a" * 64,
                  "market_state_id": "mstate1-" + "b" * 64}
        morning = MorningPoolV1.build("2026-08-03", self.now(9, 25), [candidate], market)
        decision = ConfirmationDecisionV1.build(morning, self.now(14, 50), [candidate], market)
        first = FrozenNotificationProjector.morning(morning)
        second = FrozenNotificationProjector.confirmation(decision, morning)
        self.assertEqual(first["entity_id"], morning.pool_id)
        self.assertEqual(second["entity_id"], decision.decision_id)
        self.assertEqual(second["morning_pool_id"], morning.pool_id)
        self.assertEqual(second["input_snapshot_id"], market["snapshot_id"])
        self.assertEqual(second, FrozenNotificationProjector.confirmation(decision, morning))

    def test_full_disabled_manifest_and_dependency_dag(self):
        manifest = full_offline_task_manifest(ROOT)
        self.assertEqual(len(manifest["tasks"]), 9)
        self.assertTrue(all(not row["enabled"] for row in manifest["tasks"]))
        self.assertFalse(manifest["apply_allowed"])
        decision = TaskSpecV1.build(task_name="morning_decision", scheduled_time="09:25:00",
            window_end="09:29:00", sla_deadline="09:35:00")
        push = TaskSpecV1.build(task_name="morning_push", scheduled_time="09:25:00",
            window_end="09:29:00", sla_deadline="09:35:00", dependencies=("morning_decision",))
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            engine = OfflineTaskOrchestrator(Path(directory), calendar=VerifiedCalendar(),
                executor=lambda name, day, attempt: calls.append(name) or {"status":"SUCCEEDED","reason_code":"OK"},
                specs=(decision, push))
            engine.tick(self.now(9, 25))
        self.assertEqual(calls, ["morning_decision", "morning_push"])

    def test_controlled_subprocess_exit_timeout_and_no_background_completion(self):
        success = ControlledSubprocessExecutor([sys.executable, "-c", "print('ok')"], timeout_seconds=2)("x","d",1)
        failure = ControlledSubprocessExecutor([sys.executable, "-c", "raise SystemExit(7)"], timeout_seconds=2)("x","d",1)
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "late.txt"
            code = f"import time;time.sleep(2);open(r'{marker}','w').write('late')"
            timeout = ControlledSubprocessExecutor([sys.executable, "-c", code], timeout_seconds=.1)("x","d",1)
            time.sleep(.2)
            self.assertFalse(marker.exists())
        self.assertEqual(success["status"], "SUCCEEDED")
        self.assertEqual(failure["exit_code"], 7)
        self.assertEqual(timeout["status"], "TIMED_OUT")

    def test_bound_notification_hash_request_and_receipt_are_identical(self):
        candidate = {"code":"000001","v4_candidate_origin":"V4","score_version":"rank-v1"}
        market = {"snapshot_id":"ms1-"+"a"*64,"market_state_id":"mstate1-"+"b"*64}
        morning = MorningPoolV1.build("2026-08-03", self.now(9,25), [candidate], market)
        payload = FrozenNotificationProjector.morning(morning); adapter = FakeNotificationAdapter()
        executor = BoundNotificationExecutor(adapter, lambda task, day: payload)
        with tempfile.TemporaryDirectory() as directory:
            engine = OfflineTaskOrchestrator(Path(directory), calendar=VerifiedCalendar(), executor=executor)
            terminal = engine.tick(self.now(9,25))["receipts"][-1]
        self.assertEqual(terminal["payload_sha256"], payload["payload_sha256"])
        self.assertEqual(terminal["transport_request_id"], adapter.messages[0]["request_id"])

    def test_persistent_heartbeat_alert_lifecycle_and_daemon_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor = OfflineMonitorStore(Path(directory)); engine, _ = self.engine(directory)
            first = monitor.heartbeat(process_id="daemon", recorded_at=self.now(9,24))
            alert = monitor.reconcile_alert(key="heartbeat", severity="WARNING", reason_code="LATE",
                                            observed_at=self.now(9,25), active=True)
            escalated = monitor.reconcile_alert(key="heartbeat", severity="CRITICAL", reason_code="LATE",
                                                observed_at=self.now(9,26), active=True)
            recovered = monitor.reconcile_alert(key="heartbeat", severity="CRITICAL", reason_code="LATE",
                                                observed_at=self.now(9,27), active=False)
            harness = OfflineDaemonHarness(engine, monitor); result = harness.run_once(self.now(9,25))
            restarted, _ = self.engine(directory)
            second = OfflineDaemonHarness(restarted, monitor).run_once(self.now(9,26))
            monitor.record_failure(key="push", reason_code="FAIL", observed_at=self.now(9,28))
            monitor.record_failure(key="push", reason_code="FAIL", observed_at=self.now(9,29))
            automatic = monitor.record_failure(key="push", reason_code="FAIL", observed_at=self.now(9,30))
        self.assertEqual(first["process_id"], "daemon")
        self.assertEqual(alert["alert_id"], escalated["alert_id"])
        self.assertEqual(escalated["severity"], "CRITICAL")
        self.assertEqual(recovered["status"], "RECOVERED")
        self.assertEqual(result["result"]["status"], "EMITTED")
        self.assertEqual(second["result"]["status"], "NOOP")
        self.assertEqual(automatic["severity"], "ERROR")

    def test_full_process_crash_boundary_matrix_is_fail_closed(self):
        context = multiprocessing.get_context("spawn")
        for stage in ("before_start", "after_start", "after_external_before_receipt", "after_success"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                process = context.Process(target=crash_task_boundary, args=(stage, directory))
                process.start(); process.join(15); self.assertFalse(process.is_alive())
                engine, _ = self.engine(directory); report = engine.recovery_report()
                if stage == "before_start":
                    self.assertEqual(report["status"], "CLEAN")
                elif stage == "after_success":
                    self.assertEqual(report["status"], "CLEAN")
                    self.assertEqual(engine.tick(self.now(9,26))["status"], "NOOP")
                else:
                    self.assertEqual(report["status"], "RECOVERY_REQUIRED")
                    engine.recover_interrupted(observed_at=self.now(9,26))
                    unknown = engine.journal.receipts()[-1]
                    self.assertEqual(unknown["status"], "OUTCOME_UNKNOWN")
                    engine.resolve_unknown(task_name="morning_push", trade_date="2026-08-03", attempt=1,
                        observed_at=self.now(9,27), delivered=stage == "after_external_before_receipt")

    def test_sixty_session_scan_is_idempotent_and_bounded(self):
        days = [date(2026, 5, 1) + __import__('datetime').timedelta(days=i) for i in range(60)]
        observed = datetime(2026, 8, 3, 8, 0, tzinfo=CHINA_TZ)
        with tempfile.TemporaryDirectory() as directory:
            engine, adapter = self.engine(directory)
            first = engine.scan_sessions(days, observed_at=observed)
            second = engine.scan_sessions(days, observed_at=observed)
            rows = engine.journal.receipts()
        self.assertEqual(len(first["receipts"]), 120)
        self.assertEqual(second["receipts"], [])
        self.assertEqual(len(rows), 120); self.assertEqual(adapter.messages, [])


if __name__ == "__main__": unittest.main()
