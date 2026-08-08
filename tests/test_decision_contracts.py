import json
import unittest
from datetime import datetime

from v4.decision_contracts import (
    ConfirmationDecisionV1,
    DecisionContractViolation,
    MorningPoolV1,
)
from v4.execution import CHINA_TZ


class DecisionContractTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 3, 9, 25, 0, tzinfo=CHINA_TZ)
        self.candidate = {
            "code": "000001", "name": "测试", "rank": 1, "score": 77.5,
            "v4_candidate_origin": "V4", "v4_paper_eligible": False,
            "v4_paper_block_reasons": ["规则分低于80"],
            "score_version": "test-rank-v1",
            "v4_paper_policy_version": "test-policy-v1",
        }
        self.market = {
            "data_valid": True,
            "snapshot_id": "ms1-" + "a" * 64,
            "market_state_id": "mstate1-" + "b" * 64,
        }

    def morning(self):
        return MorningPoolV1.build(
            "2026-08-03", self.now, [self.candidate], self.market
        )

    def test_entities_are_versioned_deterministic_and_serializable(self):
        first = self.morning()
        second = self.morning()
        self.assertEqual(first.pool_id, second.pool_id)
        self.assertEqual(first.schema_version, "morning-pool-v1")
        json.dumps(first.to_dict(), ensure_ascii=False)
        self.assertEqual(first.lineage["input_snapshot_id"], self.market["snapshot_id"])
        self.assertEqual(first.lineage["market_state_id"], self.market["market_state_id"])
        self.assertEqual(first.lineage["ranking_version"], "test-rank-v1")
        self.assertTrue(first.lineage["strategy_version"])
        self.assertTrue(first.lineage["policy_version"])

    def test_missing_or_mixed_lineage_is_rejected(self):
        with self.assertRaisesRegex(DecisionContractViolation, "input_snapshot_id"):
            MorningPoolV1.build("2026-08-03", self.now, [self.candidate], {})
        mixed = [self.candidate, dict(self.candidate, code="000002", score_version="other-v1")]
        with self.assertRaisesRegex(DecisionContractViolation, "mixed values"):
            MorningPoolV1.build("2026-08-03", self.now, mixed, self.market)
        missing_policy = dict(self.candidate)
        missing_policy.pop("v4_paper_policy_version")
        with self.assertRaisesRegex(DecisionContractViolation, "policy_version"):
            ConfirmationDecisionV1.build(self.morning(), self.now, [missing_policy], self.market)

    def test_confirmation_has_explicit_blocked_empty_and_buy_outcomes(self):
        morning = self.morning()
        blocked = ConfirmationDecisionV1.build(
            morning, self.now, [self.candidate], self.market
        )
        empty = ConfirmationDecisionV1.build(
            morning, self.now, [], self.market
        )
        eligible = dict(self.candidate)
        eligible["v4_paper_eligible"] = True
        eligible["v4_paper_block_reasons"] = []
        buy = ConfirmationDecisionV1.build(
            morning, self.now, [eligible], self.market
        )
        self.assertEqual(blocked.outcome, "BLOCKED")
        self.assertEqual(blocked.reason_codes, ("score_policy",))
        self.assertEqual(empty.outcome, "EMPTY")
        self.assertEqual(buy.outcome, "BUY")

    def test_confirmation_outside_mother_pool_is_rejected(self):
        outside = dict(self.candidate, code="000002")
        with self.assertRaisesRegex(DecisionContractViolation, "outside morning"):
            ConfirmationDecisionV1.build(
                self.morning(), self.now, [outside], self.market
            )

    def test_naive_entity_time_is_rejected(self):
        with self.assertRaisesRegex(DecisionContractViolation, "timezone"):
            MorningPoolV1.build(
                "2026-08-03", datetime(2026, 8, 3, 9, 25),
                [self.candidate], self.market,
            )

    def test_nested_entity_content_cannot_be_mutated(self):
        morning = self.morning()
        with self.assertRaises(TypeError):
            morning.candidates[0]["score"] = 100
        with self.assertRaises(TypeError):
            morning.market_state["data_valid"] = False

    def test_missing_morning_block_has_deterministic_hash(self):
        first = ConfirmationDecisionV1.blocked_without_morning(
            "2026-08-03", self.now, self.market
        )
        second = ConfirmationDecisionV1.blocked_without_morning(
            "2026-08-03", self.now, self.market
        )
        self.assertEqual(first.outcome, "BLOCKED")
        self.assertEqual(first.reason_codes, ("missing_morning_pool",))
        self.assertEqual(first.decision_id, second.decision_id)


if __name__ == "__main__":
    unittest.main()
