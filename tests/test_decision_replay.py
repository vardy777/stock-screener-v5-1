import json
import unittest
from pathlib import Path

from v4.decision_replay import replay_contract_case


FIXTURE = Path(__file__).parent / "fixtures" / "p2_contract_golden_2026-08-03_07.json"


class DecisionReplayTests(unittest.TestCase):
    def test_five_day_contract_golden_is_deterministic_and_consistent(self):
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 5)
        for case in cases:
            with self.subTest(trade_date=case["trade_date"]):
                first = replay_contract_case(case)
                second = replay_contract_case(case)
                self.assertEqual(first, second)
                self.assertEqual(first["replay_kind"], "synthetic_contract_golden")
                self.assertEqual(first["outcome"], case["expected_outcome"])
                self.assertIn(case["expected_reason"], first["reason_codes"])
                self.assertEqual(first["push_outcome"], first["outcome"])
                self.assertEqual(first["dashboard_outcome"], first["outcome"])
                self.assertEqual(first["execution_outcome"], first["outcome"])


if __name__ == "__main__":
    unittest.main()
