import unittest
from types import SimpleNamespace
from unittest.mock import patch

from v4.paper_policy import evaluate_paper_candidate
from v4.decision_contracts import reason_codes


class PaperPolicyTests(unittest.TestCase):
    def candidate(self, **changes):
        value = {
            "code": "000001", "rank": 1, "price": 10.0,
            "quote_time": "2026-08-03T14:50:30+08:00",
            "selection_stage": "confirmation_1450",
            "linkage_status": "confirmed_from_morning_pool",
            "v4_candidate_origin": "V4", "is_mock": False,
            "base_score": 60.0, "confirm_delta": -2.0,
            "decision_score": 58.0,
            "score_version": "v4-base-plus-confirm-delta-v1",
        }
        value.update(changes)
        return value

    @staticmethod
    def market(**changes):
        value = {
            "data_valid": True, "fresh_quote_coverage": 0.98,
            "mode_label": "neutral",
        }
        value.update(changes)
        return value

    def evaluate(self, candidate=None, market=None):
        allowed = SimpleNamespace(allowed=True, reason="处于允许窗口")
        with patch("v4.paper_policy.TradingClock.quote_is_fresh", return_value=True):
            return evaluate_paper_candidate(
                candidate or self.candidate(), market or self.market(),
                buy_status=allowed,
            )

    def test_no_arbitrary_score_cutoff_for_unbiased_top1_observation(self):
        result = self.evaluate(self.candidate(base_score=55, confirm_delta=-5,
                                              decision_score=50))
        self.assertTrue(result.eligible)
        self.assertEqual(result.policy_version, "paper-top1-integrity-v1")

    def test_coverage_risk_and_score_lineage_fail_closed(self):
        low_coverage = self.evaluate(market=self.market(fresh_quote_coverage=0.94))
        risk_off = self.evaluate(market=self.market(mode_label="risk_off"))
        broken_score = self.evaluate(self.candidate(decision_score=99))
        self.assertFalse(low_coverage.eligible)
        self.assertFalse(risk_off.eligible)
        self.assertFalse(broken_score.eligible)
        self.assertIn("确认评分血缘缺失或不一致", broken_score.reasons)

    def test_only_linked_confirmation_top1_is_eligible(self):
        self.assertFalse(self.evaluate(self.candidate(rank=2)).eligible)
        self.assertFalse(self.evaluate(self.candidate(linkage_status="missing")).eligible)

    def test_every_policy_block_has_a_stable_non_unknown_reason_code(self):
        cases = [
            self.evaluate(self.candidate(selection_stage="morning_observation")),
            self.evaluate(self.candidate(linkage_status="missing")),
            self.evaluate(self.candidate(rank=2)),
            self.evaluate(self.candidate(decision_score=99)),
            self.evaluate(market=self.market(fresh_quote_coverage=0.5)),
            self.evaluate(market=self.market(mode_label="risk_off")),
            self.evaluate(self.candidate(v4_candidate_origin="other")),
            self.evaluate(self.candidate(price=0)),
        ]
        for result in cases:
            with self.subTest(reasons=result.reasons):
                codes = reason_codes({"v4_paper_block_reasons": result.reasons})
                self.assertTrue(codes)
                self.assertNotIn("unknown_block", codes)


if __name__ == "__main__":
    unittest.main()
