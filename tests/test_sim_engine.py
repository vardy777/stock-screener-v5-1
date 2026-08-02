import json
import tempfile
import unittest
from pathlib import Path

from strategy_spec import DEFAULT_SPEC, TradeCostModel
from v3.sim_engine import BuyDecision, SimAccount
from v3.simulation import SimulationEngine


class SimAccountTests(unittest.TestCase):
    def test_simulation_engine_never_buys_mock_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = SimulationEngine()
            engine._account = SimAccount(str(Path(temp_dir) / "account.json"))
            engine._candidates = [
                {
                    "code": "000001",
                    "name": "示范数据",
                    "price": 10.0,
                    "score": 99,
                    "is_mock": True,
                }
            ]
            result = engine.execute_buy(force=True, refresh_candidates=False)
            self.assertFalse(result["success"])
            self.assertEqual(result["bought"], 0)
            self.assertEqual(engine._account.position_count, 0)

    def test_open_and_close_use_net_cash_flows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            account = SimAccount(str(Path(temp_dir) / "account.json"))
            costs = TradeCostModel(DEFAULT_SPEC)
            account.open_position("000001", "测试", 10.0, 1000)
            buy = costs.buy_cash_required(10.0, 1000)
            self.assertAlmostEqual(account.available_capital, 100_000 - buy["cash_out"], 2)

            closed = account.close_position("000001", 10.2)
            sell = costs.sell_cash_received(10.2, 1000)
            self.assertAlmostEqual(
                account.available_capital,
                100_000 - buy["cash_out"] + sell["cash_in"],
                2,
            )
            self.assertAlmostEqual(
                closed["pnl_amount"], sell["cash_in"] - buy["cash_out"], 2
            )
            self.assertIn("stamp_duty", closed)

    def test_buy_decision_caps_each_position_and_blocks_risk_off(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            account = SimAccount(str(Path(temp_dir) / "account.json"))
            candidates = [
                {"code": f"00000{i}", "name": f"测试{i}", "price": 10 + i, "final_score": 90 - i}
                for i in range(1, 5)
            ]
            blocked = BuyDecision.select(candidates, account, {"mode_label": "risk_off"})
            self.assertEqual(blocked, [])

            decisions = BuyDecision.select(candidates, account, {"mode_label": "neutral"})
            self.assertEqual(len(decisions), 1)
            cap = DEFAULT_SPEC.position_budget(account.total_equity)
            for decision in decisions:
                self.assertLessEqual(decision["estimated_cash_out"], cap + 0.01)
                self.assertEqual(decision["shares"] % 100, 0)


if __name__ == "__main__":
    unittest.main()
