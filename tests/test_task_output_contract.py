import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from v4.p4_contracts import TaskContractViolation
from v4.task_output_contract import OUTPUT_KINDS, TaskOutputV1, audit_output_chain


NOW = datetime(2026, 8, 10, 9, 25, tzinfo=ZoneInfo("Asia/Shanghai"))


class TaskOutputContractTests(unittest.TestCase):
    def output(self, task, entity_id, inputs=()):
        payload = {"id": entity_id, "task": task}
        return TaskOutputV1.build(task_name=task, trade_date="2026-08-10",
            status="SUCCEEDED", reason_code="OK", recorded_at=NOW,
            entity_kind=OUTPUT_KINDS[task], entity_id=entity_id,
            entity_payload=payload, input_ids=inputs)

    def test_success_requires_task_specific_entity_and_payload(self):
        with self.assertRaisesRegex(TaskContractViolation, "MorningPoolV1 required"):
            TaskOutputV1.build(task_name="morning_decision", trade_date="2026-08-10",
                status="SUCCEEDED", reason_code="OK", recorded_at=NOW,
                entity_kind="Wrong", entity_id="x", entity_payload={})
        with self.assertRaisesRegex(TaskContractViolation, "payload required"):
            TaskOutputV1.build(task_name="health_check", trade_date="2026-08-10",
                status="SUCCEEDED", reason_code="OK", recorded_at=NOW,
                entity_kind="HealthReportV1", entity_id="health-1")

    def test_failed_output_is_still_immutable_and_restart_auditable(self):
        row = TaskOutputV1.build(task_name="paper_sell", trade_date="2026-08-10",
            status="FAILED", reason_code="NO_OPEN_POSITION", recorded_at=NOW)
        self.assertEqual(row, TaskOutputV1.from_mapping(row.to_dict()))
        changed = row.to_dict(); changed["reason_code"] = "OTHER"
        with self.assertRaisesRegex(TaskContractViolation, "content hash mismatch"):
            TaskOutputV1.from_mapping(changed)

    def test_chain_enforces_final_entity_lineage(self):
        morning = self.output("morning_decision", "mp-1")
        push = self.output("morning_push", "notification-1", ("mp-1",))
        feature = self.output("feature_freeze", "fc1-1")
        decision = self.output("confirmation_decision", "cd-1", ("mp-1", "fc1-1"))
        buy = self.output("paper_buy", "pexec-1", ("cd-1",))
        self.assertTrue(audit_output_chain([morning, push, feature, decision, buy])["passed"])
        broken = self.output("paper_buy", "pexec-2")
        report = audit_output_chain([morning, feature, decision, broken])
        self.assertFalse(report["passed"])
        self.assertIn("MISSING_INPUT_LINEAGE:paper_buy:confirmation_decision", report["issues"])

    def test_naive_datetime_is_rejected(self):
        with self.assertRaisesRegex(TaskContractViolation, "timezone required"):
            TaskOutputV1.build(task_name="maintenance", trade_date="2026-08-10",
                status="FAILED", reason_code="TEST", recorded_at="2026-08-10T15:10:00")


if __name__ == "__main__":
    unittest.main()
