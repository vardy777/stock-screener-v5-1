import json,tempfile,unittest
from pathlib import Path
from v4.production_task_runner import COMMANDS
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

if __name__=="__main__": unittest.main()
