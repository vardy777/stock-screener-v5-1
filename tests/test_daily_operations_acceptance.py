import tempfile,unittest
import hashlib,json
from pathlib import Path
from unittest.mock import patch
from v4.daily_operations_acceptance import build

class DailyOperationsAcceptanceTests(unittest.TestCase):
    def test_missing_real_session_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, patch("v4.daily_operations_acceptance.windows_time_status",return_value={"passed":False}):
            report=build(Path(directory),"2026-08-12")
        self.assertFalse(report["passed"])
        self.assertEqual(set(report["missing_tasks"]),set(("morning_decision","morning_push","feature_freeze","confirmation_decision","confirmation_push","paper_buy","health_check","maintenance")))

    def test_push_acceptance_reads_immutable_notification_not_legacy_index(self):
        with tempfile.TemporaryDirectory() as directory, patch("v4.daily_operations_acceptance.windows_time_status",return_value={"passed":True}):
            root=Path(directory); key="v4-morning:2026-08-12"; safe=hashlib.sha256(key.encode()).hexdigest()[:24]
            path=root/"v4/data/notifications"/f"{safe}.json"; path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"schema_version":"notification-receipt-v1","outcome":"ACCEPTED","response_code":200,
                "parent_entity_id":"mp-x","transport_request_id":"request","notification_id":"notification1-x"}),encoding="utf-8")
            journal=root/"v4/data/candidate_journal/2026-08-12.json"; journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps({"trade_date":"2026-08-12","morning":{"pool_id":"mp-x"}}),encoding="utf-8")
            report=build(root,"2026-08-12")
        self.assertTrue(report["push_checks"][0]["passed"])

if __name__=="__main__": unittest.main()
