import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from v4.daily_operations_acceptance import build

class DailyOperationsAcceptanceTests(unittest.TestCase):
    def test_missing_real_session_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, patch("v4.daily_operations_acceptance.windows_time_status",return_value={"passed":False}):
            report=build(Path(directory),"2026-08-12")
        self.assertFalse(report["passed"])
        self.assertEqual(set(report["missing_tasks"]),set(("morning_decision","morning_push","feature_freeze","confirmation_decision","confirmation_push","paper_buy","health_check","maintenance")))

if __name__=="__main__": unittest.main()
