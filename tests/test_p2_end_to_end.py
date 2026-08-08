import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from v4 import dashboard
from v4.candidate_journal import CandidateJournal
from v4.decision_service import DecisionChainService, execution_directive
from v4.push import build_afternoon_card
from v4.runtime import V4Runtime
from v4.execution import CHINA_TZ
from v4.scripts import afternoon_push


class P2EndToEndTests(unittest.TestCase):
    @staticmethod
    def market():
        return {
            "data_valid": True, "fresh_quote_coverage": 0.98,
            "quote_coverage": 0.98, "mode_label": "neutral",
            "advance_ratio": 0.55, "market_mean_signal_return": 0.001,
            "market_mean_gap": 0.0,
        }

    @staticmethod
    def morning_candidate():
        return {
            "code": "000001", "name": "测试", "rank": 1,
            "price": 10.0, "quote_time": "2026-08-03T14:50:30+08:00",
            "base_score": 62.0, "confirm_delta": 0.0,
            "decision_score": 62.0, "score": 62.0, "final_score": 62.0,
            "score_version": "v4-causal-rule-rank-v1",
            "selection_stage": "morning_observation",
            "candidate_source": "v4-causal-rule-rank-v1",
            "v4_candidate_origin": "V4", "v4_research_ranked": True,
            "v4_features": {"signal_return": 0.01,
                            "signal_close_position": 0.6,
                            "volume_ratio_20": 1.0},
        }

    @classmethod
    def confirmation_candidate(cls):
        value = cls.morning_candidate()
        value.update({
            "base_score": 62.0, "confirm_delta": 1.0,
            "decision_score": 63.0, "score": 63.0, "final_score": 63.0,
            "score_version": "v4-base-plus-confirm-delta-v1",
            "selection_stage": "confirmation_1450",
            "v4_paper_market_valid": True,
            "v4_paper_market_mode": "neutral",
        })
        return value

    def test_frozen_chain_drives_push_dashboard_and_execution_consistently(self):
        allowed = SimpleNamespace(allowed=True, reason="处于允许窗口", to_dict=lambda: {})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = CandidateJournal(root / "v4" / "data" / "candidate_journal")
            runtime = V4Runtime()
            service = DecisionChainService(journal, runtime)
            with (
                patch("v4.runtime.TradingClock.action_status", return_value=allowed),
                patch("v4.runtime.TradingClock.quote_is_fresh", return_value=True),
                patch("v4.runtime.save_runtime_state"),
            ):
                morning = service.publish_morning(
                    "2026-08-03", [self.morning_candidate()], self.market()
                )
                decision = service.publish_confirmation(
                    "2026-08-03", [self.confirmation_candidate()], self.market()
                )
                repeated = service.publish_confirmation(
                    "2026-08-03", [self.confirmation_candidate()], self.market()
                )
            self.assertEqual(morning["schema_version"], "morning-pool-v1")
            self.assertEqual(decision["outcome"], "BUY")
            self.assertEqual(decision["decision_id"], repeated["decision_id"])

            card = build_afternoon_card(
                decision["candidates"], decision["market_state"], [],
                decision=decision,
            )
            directive = execution_directive(decision)
            with patch.object(dashboard, "PROJECT_ROOT", root):
                view = dashboard._load_paper_automation_status()
            self.assertIn(decision["decision_id"], card)
            self.assertTrue(directive["execute_buy"])
            self.assertEqual(directive["decision_id"], decision["decision_id"])
            self.assertEqual(view["confirmation_outcome"], "BUY")
            self.assertEqual(view["confirmation_decision_id"], decision["decision_id"])

    def test_atomic_publication_failure_leaves_no_partial_entity_and_can_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CandidateJournal(Path(directory))
            with patch("pathlib.Path.replace", side_effect=OSError("disk failure")):
                with self.assertRaisesRegex(OSError, "disk failure"):
                    journal.save_morning(
                        "2026-08-03", [self.morning_candidate()], self.market()
                    )
            self.assertFalse(journal.path_for("2026-08-03").exists())
            self.assertFalse(journal.path_for("2026-08-03").with_suffix(".tmp").exists())
            saved = journal.save_morning(
                "2026-08-03", [self.morning_candidate()], self.market()
            )
            self.assertTrue(saved["morning"]["pool_id"].startswith("mp-"))

    def test_push_failure_and_dashboard_read_do_not_mutate_final_decision(self):
        allowed = SimpleNamespace(allowed=True, reason="处于允许窗口", to_dict=lambda: {})
        fixed = datetime(2026, 8, 3, 14, 50, 30, tzinfo=CHINA_TZ)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = CandidateJournal(root / "v4" / "data" / "candidate_journal")
            service = DecisionChainService(journal, V4Runtime())
            with (
                patch.object(CandidateJournal, "_now", return_value=fixed),
                patch("v4.runtime.TradingClock.action_status", return_value=allowed),
                patch("v4.runtime.TradingClock.quote_is_fresh", return_value=True),
                patch("v4.runtime.save_runtime_state"),
            ):
                service.publish_morning(
                    "2026-08-03", [self.morning_candidate()], self.market()
                )
                decision = service.publish_confirmation(
                    "2026-08-03", [self.confirmation_candidate()], self.market()
                )
            journal_path = journal.path_for("2026-08-03")
            before = journal_path.read_bytes()
            engine = SimpleNamespace(
                load_state=lambda: None,
                screen_today=lambda stage: decision["candidates"],
                positions=[],
            )
            with (
                patch.object(afternoon_push, "_now", return_value=fixed),
                patch.object(afternoon_push, "_in_window", return_value=True),
                patch.object(afternoon_push, "TradingCalendar") as calendar,
                patch.object(afternoon_push, "SimulationEngine", return_value=engine),
                patch.object(afternoon_push, "CandidateJournal", return_value=journal),
                patch.object(afternoon_push, "send_wechat", return_value=False),
            ):
                calendar.return_value.is_open.return_value = True
                self.assertEqual(afternoon_push.main(), 1)
            self.assertEqual(journal_path.read_bytes(), before)

            with patch.object(dashboard, "PROJECT_ROOT", root):
                view = dashboard._load_paper_automation_status()
            self.assertEqual(view["confirmation_decision_id"], decision["decision_id"])
            self.assertEqual(journal_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
