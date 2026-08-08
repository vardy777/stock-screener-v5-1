import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from v3.push import build_afternoon_card, build_morning_card, send_wechat
from v3 import dashboard
from v3.scripts import afternoon_push, morning_push


ROOT = Path(__file__).resolve().parent.parent


class LocalRuntimeMigrationTests(unittest.TestCase):
    def test_runtime_files_have_no_hermes_dependency(self):
        for relative in (
            "start_dashboard.py",
            "main.py",
            "v2/config.py",
            "v3/config.py",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8").lower()
            self.assertNotIn("hermes", content, relative)

    def test_windows_tasks_include_both_required_pushes(self):
        content = (
            ROOT / "phase1" / "scripts" / "register_v4_snapshot_tasks.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("AStock-V4-Push-Morning-0925", content)
        self.assertIn('At = "09:25"', content)
        self.assertIn("AStock-V4-Push-Confirm-145020", content)
        self.assertIn('At = "14:50:20"', content)
        self.assertIn("-LogonType S4U", content)
        self.assertIn("-StartWhenAvailable", content)

    def test_dashboard_get_state_never_triggers_market_screening(self):
        engine = MagicMock()
        engine.load_candidates_from_file.return_value = [
            {"code": "000001", "strategy": "追高", "v4_tradable": False}
        ]
        engine.load_market_state_from_file.return_value = {
            "mode_label": "neutral", "data_valid": False
        }
        engine.get_state.return_value = {
            "account": {}, "positions": [], "candidates": [],
            "trade_history": [], "daily_records": [],
            "market_state": {"mode_label": "unavailable"},
            "sector_ranks": {"top": []}, "sentiment": {}, "time": "",
        }
        runtime = MagicMock()
        runtime.system_state.return_value = {
            "readiness": {"trade_enabled": False},
            "clock": {"buy": {"allowed": False}},
        }
        with patch.object(dashboard, "SimulationEngine", return_value=engine):
            with patch("v4.runtime.V4Runtime", return_value=runtime):
                dashboard._fresh_engine_state(force=True)
        engine.screen_today.assert_not_called()

    def test_legacy_caches_resolve_inside_project(self):
        from v3 import config

        for path in (config.PE_PB_CACHE, config.WIN_RATE, config.MARKET_DB):
            resolved = Path(path).resolve()
            self.assertTrue(resolved.is_relative_to(ROOT))
            self.assertTrue(resolved.exists())

    def test_morning_card_is_observation_not_buy_instruction(self):
        card = build_morning_card(
            [{"code": "000001", "name": "测试", "score": 88, "pct_chg": 1.2}],
            {"mode_label": "neutral"},
            [{"code": "600000", "name": "持仓", "buy_price": 10.0}],
        )
        self.assertIn("000001", card)
        self.assertIn("尾盘确认", card)
        self.assertIn("早盘不买入", card)
        self.assertIn("09:30待卖持仓", card)

    def test_afternoon_card_only_confirms_v4_tradable_top1(self):
        card = build_afternoon_card(
            [
                {
                    "code": "000001", "name": "测试", "score": 90,
                    "v4_tradable": True, "v4_shadow_confidence": 0.7,
                    "v4_block_reasons": [], "v4_paper_eligible": True,
                    "v4_paper_block_reasons": [], "morning_rank": 1, "rank": 1,
                },
                {
                    "code": "000002", "name": "观察", "score": 89,
                    "v4_tradable": False, "v4_shadow_confidence": 0.6,
                    "v4_block_reasons": ["精度优先仅允许Top1"],
                    "v4_paper_eligible": False,
                    "v4_paper_block_reasons": ["模拟观测仅执行Top1"],
                    "morning_rank": 2, "rank": 2,
                },
            ],
            {"mode_label": "neutral"},
            [],
        )
        self.assertIn("唯一确认Top1", card)
        self.assertIn("000001", card)
        self.assertIn("模拟观测仅执行Top1", card)

    @patch("v3.push.PUSHPLUS_TOKEN", "test-token")
    def test_pushplus_requires_api_acceptance(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"code": 500, "msg": "rejected"}
        ).encode("utf-8")
        with patch("v3.push.urllib.request.urlopen", return_value=response):
            with patch("v3.push.time.sleep"):
                self.assertFalse(send_wechat("test", "body"))
        response.__enter__.return_value.read.return_value = json.dumps(
            {"code": 200, "msg": "ok"}
        ).encode("utf-8")
        with patch("v3.push.urllib.request.urlopen", return_value=response):
            self.assertTrue(send_wechat("test", "body"))

    @patch("v3.push.PUSHPLUS_TOKEN", "test-token")
    def test_pushplus_message_key_suppresses_duplicate_delivery(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"code": 200, "msg": "ok"}
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            receipt = Path(temp_dir) / "receipts.json"
            with patch("v3.push.PUSH_RECEIPT_PATH", receipt):
                with patch(
                    "v3.push.urllib.request.urlopen", return_value=response
                ) as urlopen:
                    self.assertTrue(
                        send_wechat("test", "body", message_key="morning:2026-08-03")
                    )
                    self.assertTrue(
                        send_wechat("test", "body", message_key="morning:2026-08-03")
                    )
                    self.assertEqual(urlopen.call_count, 1)

    @patch("v3.push.PUSHPLUS_TOKEN", "test-token")
    def test_pushplus_dry_run_never_calls_network(self):
        with patch.dict(os.environ, {"PUSHPLUS_DRY_RUN": "true"}):
            with patch("v3.push.urllib.request.urlopen") as urlopen:
                self.assertTrue(send_wechat("test", "body"))
                urlopen.assert_not_called()

    def test_morning_job_generates_candidates_before_push(self):
        engine = MagicMock()
        engine.screen_today.return_value = [
            {
                "code": "000001", "name": "测试", "score": 88,
                "pct_chg": 1.0, "v4_candidate_origin": "V4",
                "candidate_source": "v4-causal-rule-rank-v1",
            }
        ]
        engine._get_market_state.return_value = {"mode_label": "neutral"}
        engine.positions = []
        with patch.object(morning_push, "SimulationEngine", return_value=engine):
            with patch.object(morning_push, "TradingCalendar") as calendar:
                calendar.return_value.is_open.return_value = True
                with patch.object(morning_push, "_in_window", return_value=True):
                    with patch.object(morning_push, "send_wechat", return_value=True) as send:
                        self.assertEqual(morning_push.main(), 0)
        engine.screen_today.assert_called_once_with(stage="morning")
        send.assert_called_once()

    def test_afternoon_job_recalculates_before_confirmation(self):
        engine = MagicMock()
        engine.screen_today.return_value = [
            {
                "code": "000001", "name": "测试", "score": 88,
                "v4_tradable": False, "v4_block_reasons": ["研究准入未通过"],
                "v4_candidate_origin": "V4",
                "candidate_source": "v4-causal-rule-rank-v1",
            }
        ]
        engine._get_market_state.return_value = {"mode_label": "neutral"}
        engine.positions = []
        with patch.object(afternoon_push, "SimulationEngine", return_value=engine):
            with patch.object(afternoon_push, "TradingCalendar") as calendar:
                calendar.return_value.is_open.return_value = True
                with patch.object(afternoon_push, "_in_window", return_value=True):
                    with patch.object(afternoon_push, "send_wechat", return_value=True) as send:
                        self.assertEqual(afternoon_push.main(), 0)
        engine.screen_today.assert_called_once_with(stage="confirmation")
        send.assert_called_once()

    def test_compatibility_engine_contains_no_v3_selection_fallback(self):
        content = (ROOT / "v3" / "simulation.py").read_text(encoding="utf-8")
        self.assertNotIn("UltraShortScorer", content)
        self.assertNotIn("UltraShortFactorComputer", content)
        self.assertNotIn("PullbackEngine", content)
        self.assertNotIn("fallback_candidates=top5", content)
        dashboard_content = (ROOT / "v3" / "dashboard.py").read_text(encoding="utf-8")
        self.assertNotIn("from v3.pullback import", dashboard_content)


if __name__ == "__main__":
    unittest.main()
