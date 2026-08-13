import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from v4.production_task_runner import COMMANDS,_inside_task_window
from v4.task_output_contract import OUTPUT_KINDS

class ProductionTaskBindingTests(unittest.TestCase):
    def test_all_nine_tasks_have_real_binding_and_paper_uses_batch_contract(self):
        expected={"morning_decision","morning_push","paper_sell","feature_freeze","confirmation_decision",
                  "confirmation_push","paper_buy","health_check","maintenance"}
        self.assertEqual(set(COMMANDS)|{"paper_buy","paper_sell"},expected)
        self.assertEqual(OUTPUT_KINDS["paper_buy"],"PaperExecutionBatchV1")
        self.assertEqual(OUTPUT_KINDS["paper_sell"],"PaperExecutionBatchV1")
        source=Path(__file__).resolve().parents[1]/"v4"/"production_task_runner.py"
        text=source.read_text(encoding="utf-8")
        self.assertNotIn("v3.",text); self.assertIn("DEPENDENCY_NOT_SUCCEEDED",text)

    def test_task_windows_fail_closed_after_missed_schedule(self):
        tz=ZoneInfo("Asia/Shanghai")
        self.assertTrue(_inside_task_window("morning_decision",datetime(2026,8,13,9,25,tzinfo=tz)))
        self.assertFalse(_inside_task_window("morning_decision",datetime(2026,8,13,12,0,tzinfo=tz)))
        self.assertTrue(_inside_task_window("confirmation_decision",datetime(2026,8,13,14,50,20,tzinfo=tz)))
        self.assertFalse(_inside_task_window("confirmation_decision",datetime(2026,8,13,15,0,tzinfo=tz)))
        self.assertFalse(_inside_task_window("paper_buy",datetime(2026,8,13,14,52,tzinfo=tz)))

    def test_dashboard_runner_tracks_child_for_failed_start_cleanup(self):
        source=Path(__file__).resolve().parents[1]/"phase1"/"scripts"/"run_p5_dashboard.ps1"
        text=source.read_text(encoding="utf-8")
        self.assertIn("-PassThru",text)
        self.assertIn("Stop-Process -Id $process.Id",text)
        self.assertIn("Select-Object -ExpandProperty OwningProcess -Unique",text)
        self.assertIn("param([switch]$Restart)",text)
        self.assertIn("if (-not $Restart) { exit 0 }",text)
        root=Path(__file__).resolve().parents[1]
        self.assertIn("[TimeSpan]::Zero",(root/"scripts"/"apply_production_cutover.ps1").read_text(encoding="utf-8"))
        self.assertIn("[TimeSpan]::Zero",(root/"phase1"/"scripts"/"register_v4_snapshot_tasks.ps1").read_text(encoding="utf-8"))

if __name__=="__main__": unittest.main()
