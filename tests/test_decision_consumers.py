import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from v4.simulation import SimulationEngine
from v4.scripts import afternoon_push, morning_push
from v4.candidate_journal import CandidateJournal
from v4.execution import CHINA_TZ


class DecisionConsumerTests(unittest.TestCase):
    @staticmethod
    def candidate(eligible=True):
        return {
            "code": "000001", "name": "测试", "rank": 1, "score": 88,
            "price": 10.0, "quote_time": "2026-08-03T14:50:30+08:00",
            "v4_candidate_origin": "V4", "v4_paper_eligible": eligible,
            "v4_paper_block_reasons": [] if eligible else ["规则分低于80"],
            "candidate_source": "v4-causal-rule-rank-v1",
            "score_version": "v4-base-plus-confirm-delta-v1",
            "v4_paper_policy_version": "test-policy-v1",
        }

    def test_morning_push_reads_persisted_morning_entity(self):
        engine = MagicMock()
        engine.positions = []
        journal = MagicMock()
        journal.morning.return_value = {
            "candidates": [self.candidate()], "market_state": {"mode_label": "neutral"}
        }
        with (
            patch.object(morning_push, "SimulationEngine", return_value=engine),
            patch.object(morning_push, "CandidateJournal", return_value=journal),
            patch.object(morning_push, "TradingCalendar") as calendar,
            patch.object(morning_push, "_in_window", return_value=True),
            patch.object(morning_push, "send_wechat", return_value=True) as send,
        ):
            calendar.return_value.is_open.return_value = True
            self.assertEqual(morning_push.main(), 0)
        engine.screen_today.assert_called_once_with(stage="morning")
        send.assert_called_once()

    def test_afternoon_push_reads_final_confirmation_entity(self):
        engine = MagicMock()
        engine.positions = []
        journal = MagicMock()
        journal.confirmation.return_value = {
            "decision_id": "cd-test", "outcome": "BLOCKED",
            "reason_codes": ["score_policy"],
            "candidates": [self.candidate(False)],
            "market_state": {"mode_label": "neutral"},
        }
        with (
            patch.object(afternoon_push, "SimulationEngine", return_value=engine),
            patch.object(afternoon_push, "CandidateJournal", return_value=journal),
            patch.object(afternoon_push, "TradingCalendar") as calendar,
            patch.object(afternoon_push, "_in_window", return_value=True),
            patch.object(afternoon_push, "send_wechat", return_value=True) as send,
        ):
            calendar.return_value.is_open.return_value = True
            self.assertEqual(afternoon_push.main(), 0)
        engine.screen_today.assert_called_once_with(stage="confirmation")
        card = send.call_args.args[1]
        self.assertIn("BLOCKED", card)
        self.assertIn("cd-test", card)

    def test_paper_buy_refuses_candidate_cache_without_final_decision(self):
        engine = SimulationEngine()
        engine._account = MagicMock()
        engine._candidates = [self.candidate(True)]
        journal = MagicMock()
        journal.confirmation.return_value = {}
        with (
            patch("v4.execution.TradingClock.require"),
            patch("v4.candidate_journal.CandidateJournal", return_value=journal),
        ):
            result = engine.execute_buy(
                force=True, refresh_candidates=False, paper_observation=True
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["decision"], "missing")

    def test_blocked_final_decision_cannot_be_overridden_by_cache(self):
        engine = SimulationEngine()
        engine._account = MagicMock()
        engine._candidates = [self.candidate(True)]
        journal = MagicMock()
        journal.confirmation.return_value = {
            "decision_id": "cd-blocked", "outcome": "BLOCKED",
            "reason_codes": ["score_policy"], "candidates": [self.candidate(False)],
            "market_state": {"mode_label": "neutral"},
        }
        with (
            patch("v4.execution.TradingClock.require"),
            patch("v4.candidate_journal.CandidateJournal", return_value=journal),
        ):
            result = engine.execute_buy(
                force=True, refresh_candidates=False, paper_observation=True
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["bought"], 0)
        self.assertEqual(result["decision_id"], "cd-blocked")
        engine._account._save.assert_not_called()

    def test_buy_execution_consumes_persisted_buy_decision_id(self):
        fixed = datetime(2026, 8, 3, 14, 50, 45, tzinfo=CHINA_TZ)
        candidate = self.candidate(True)
        candidate.update({
            "selection_stage": "confirmation_1450",
            "linkage_status": "confirmed_from_morning_pool",
            "base_score": 60.0, "confirm_delta": 1.0,
            "decision_score": 61.0,
            "score_version": "v4-base-plus-confirm-delta-v1",
        })
        with tempfile.TemporaryDirectory() as directory:
            journal = CandidateJournal(Path(directory))
            morning = dict(candidate, selection_stage="morning_observation",
                           score_version="v4-causal-rule-rank-v1")
            with patch.object(CandidateJournal, "_now", return_value=fixed):
                market = {"snapshot_id": "ms1-" + "a" * 64,
                          "market_state_id": "mstate1-" + "b" * 64}
                journal.save_morning("2026-08-03", [morning], market)
                journal.save_confirmation("2026-08-03", [candidate], market)
            decision = journal.confirmation("2026-08-03")

            engine = SimulationEngine()
            engine._account = MagicMock()
            engine._account._save = MagicMock()
            selected = [{"code": "000001", "shares": 100, "buy_price": 10.0}]
            with (
                patch("v4.execution.TradingClock.require"),
                patch("v4.execution.TradingClock.now", return_value=fixed),
                patch("v4.candidate_journal.JOURNAL_DIR", Path(directory)),
                patch("v4.simulation.BuyDecision.select", return_value=selected),
                patch("v4.simulation.BuyDecision.execute", return_value=1),
            ):
                result = engine.execute_buy(
                    force=True, refresh_candidates=False, paper_observation=True
                )
        self.assertTrue(result["success"])
        self.assertEqual(result["bought"], 1)
        self.assertEqual(result["decision_id"], decision["decision_id"])


if __name__ == "__main__":
    unittest.main()
