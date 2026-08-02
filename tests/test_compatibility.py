import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from v3.settlement import SettlementEngine
from v3.watchlist import WATCHLIST, scan_all
from v3.watchlist_cache import load_cache, save_cache


class CompatibilityEntrypointTests(unittest.TestCase):
    def test_scheduler_modules_are_importable(self):
        from v3.scripts import afternoon_push  # noqa: F401
        from v3.scripts import daily_settlement  # noqa: F401
        from v3.scripts import morning_push  # noqa: F401
        from v3.scripts import watchlist_scan  # noqa: F401

    def test_v3_settlement_reads_the_same_journal_written_by_v3_commands(self):
        from config import JOURNAL_PATH as ROOT_JOURNAL
        from v3.config import JOURNAL_PATH as V3_JOURNAL

        self.assertEqual(Path(V3_JOURNAL).resolve(), Path(ROOT_JOURNAL).resolve())

    def test_watchlist_failure_never_invents_prices(self):
        with patch("v3.watchlist.fetch_quote", return_value=None):
            results = scan_all()
        self.assertEqual(len(results), len(WATCHLIST))
        self.assertTrue(all(item["level"] == "error" for item in results))
        self.assertTrue(all(item["price"] == 0 for item in results))

    def test_watchlist_cache_round_trip_is_atomic_and_list_shaped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "watchlist.json"
            expected = [{"code": "000001", "price": 10.0}]
            save_cache(expected, path)
            self.assertEqual(load_cache(path), expected)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_settlement_is_persistent_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settlement.json"
            engine = SettlementEngine(str(path))
            engine.record("1", 10.0, 11.0, "2026-08-01")
            engine.record("1", 10.0, 11.0, "2026-08-01")
            engine.record("2", 10.0, 9.0, "2026-08-01")

            summary = SettlementEngine(str(path)).summary()
            self.assertEqual(summary["trades"], 2)
            self.assertEqual(summary["wins"], 1)
            self.assertEqual(summary["win_rate"], 0.5)
            self.assertAlmostEqual(summary["total_return"], 0.0)

    def test_sim_plan_uses_v4_locked_candidates_without_undefined_names(self):
        class Account:
            position_count = 0
            available_capital = 100_000.0
            total_equity = 100_000.0
            cumulative_return = 0.0
            data = {"initial_capital": 100_000.0}

        class Engine:
            account = Account()
            positions = []

            def load_state(self):
                return None

            def screen_today(self):
                return [
                    {
                        "code": "000001",
                        "name": "测试",
                        "price": 10.0,
                        "score": 90.0,
                        "v4_tradable": False,
                        "v4_decision": "观察/空仓",
                        "v4_block_reasons": ["研究准入未通过"],
                    }
                ]

            def _get_market_state(self):
                return {"mode_label": "neutral"}

        class Runtime:
            def system_state(self, market):
                return {
                    "system_version": "4.0.0-research",
                    "pipeline_id": "overnight-1450-0930",
                    "readiness": {
                        "headline": "V4研究锁定",
                        "status": "research_locked",
                        "trade_enabled": False,
                    },
                    "clock": {"buy": {"reason": "不在执行窗口"}},
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "trade_plan.json"
            plan = main.cmd_sim_plan(
                engine=Engine(), runtime=Runtime(), output_path=output
            )
            saved = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(plan["buy_plan"], [])
        self.assertEqual(saved["readiness"]["status"], "research_locked")
        self.assertEqual(saved["candidates"][0]["v4_tradable"], False)


if __name__ == "__main__":
    unittest.main()
