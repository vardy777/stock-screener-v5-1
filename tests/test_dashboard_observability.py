import unittest
from unittest.mock import patch

import pandas as pd

from decision_policy import adaptive_strategy_decision
from v3.dashboard import build_html, _compute_validation_summary
from v3.market import MarketContext
from v3.simulation import SimulationEngine


class AdaptiveStrategyTests(unittest.TestCase):
    def test_invalid_market_snapshot_always_observes(self):
        result = adaptive_strategy_decision(
            {
                "data_valid": False,
                "fresh_quote_coverage": 0.62,
                "advance_ratio": 0.8,
                "market_mean_signal_return": 0.02,
            }
        )
        self.assertEqual(result["key"], "observe")
        self.assertEqual(result["candidate_strategies"], [])

    def test_strong_broad_market_prefers_chase_research_pool(self):
        result = adaptive_strategy_decision(
            {
                "data_valid": True,
                "fresh_quote_coverage": 0.98,
                "advance_ratio": 0.68,
                "market_mean_signal_return": 0.009,
                "market_mean_gap": 0.001,
                "regime_score": 0.7,
                "mode_label": "risk_on",
            },
            {"score": 7},
        )
        self.assertEqual(result["key"], "chase")
        self.assertEqual(result["candidate_strategies"], ["追高"])

    def test_narrow_neutral_market_prefers_pullback_research_pool(self):
        result = adaptive_strategy_decision(
            {
                "data_valid": True,
                "fresh_quote_coverage": 0.98,
                "advance_ratio": 0.49,
                "market_mean_signal_return": 0.001,
                "market_mean_gap": 0.0,
                "regime_score": 0.0,
                "mode_label": "neutral",
            }
        )
        self.assertEqual(result["key"], "pullback")

    def test_low_coverage_name_mapping_cannot_change_candidate_score(self):
        context = MarketContext()
        context._rankings = {
            "计算机": {"rank": 1},
            **{f"板块{i}": {"rank": i + 1} for i in range(1, 15)},
        }
        context._top_sectors = ["计算机"]
        context._classified_coverage = 0.16
        self.assertFalse(context.classification_reliable)
        self.assertEqual(context.get_sector_bonus("计算机股份"), 0.0)
        context._classified_coverage = 0.8
        self.assertTrue(context.classification_reliable)
        self.assertEqual(context.get_sector_bonus("计算机股份"), 10)


class DashboardEvidenceTests(unittest.TestCase):
    @staticmethod
    def _state():
        history = [
            {"pnl_amount": 100.0, "pnl_pct": 1.0, "code": "000001", "name": "甲", "buy_price": 10.0, "sell_price": 10.1},
            {"pnl_amount": -200.0, "pnl_pct": -2.0, "code": "000002", "name": "乙", "buy_price": 10.0, "sell_price": 9.8},
        ]
        state = {
            "account": {
                "total_return_pct": -0.1,
                "today_pnl_pct": 0.0,
                "current_capital": 99900.0,
                "total_equity": 99900.0,
                "initial_capital": 100000.0,
                "position_market_value": 0.0,
                "position_count": 0,
                "total_trades": 2,
                "win_rate": 50.0,
                "max_drawdown_pct": 0.2,
            },
            "market_state": {
                "mode_label": "unavailable",
                "observed_mode_label": "neutral",
                "data_valid": False,
                "market_equal_weight_pct": 0.2,
                "market_median_pct": 0.1,
                "advance_ratio": 0.51,
                "regime_score": 0.02,
                "market_total_amount_yi": 10000.0,
                "quote_coverage": 0.9,
                "fresh_quote_coverage": 0.0,
                "observed_codes": 4000,
                "expected_codes": 4400,
                "as_of": "2026-08-01T15:00:00+08:00",
            },
            "time": "2026-08-02 12:00:00",
            "positions": [],
            "candidates": [{
                "code": "000001", "name": "测试", "rank": 1,
                "score": 88.0, "change_pct": 5.0, "price": 10.0,
                "buy_price": 10.02, "strategy": "追高",
                "quote_time": "2026-08-01T15:00:00+08:00",
                "v4_tradable": False, "v4_decision": "观察/空仓",
                "v4_block_reasons": ["研究准入未通过"],
                "v4_shadow_confidence": 0.8,
            }],
            "sector_ranks": {},
            "sentiment": {"score": 5, "label": "中性", "up_ratio": 0.51},
            "daily_records": [],
            "trade_history": history,
            "research": {"available": False, "summary": {}},
            "fund_flow": {"status": "stale", "current": False},
            "v4": {
                "readiness": {"trade_enabled": False, "checks": [], "status": "research_locked"},
                "clock": {"buy": {"reason": "研究锁定"}, "sell": {"allowed": False, "reason": "周末休市"}},
                "scheduler_contract_preserved": True,
            },
            "strategy_policy": {"key": "observe", "label": "观望 / 空仓", "candidate_strategies": [], "reasons": ["数据无效"]},
            "trade_allowed": False,
        }
        state["validation"] = _compute_validation_summary(state)
        return state

    def test_validation_keeps_legacy_and_proxy_cohorts_separate(self):
        summary = _compute_validation_summary(self._state())
        self.assertEqual(summary["legacy_simulation"]["trades"], 2)
        self.assertEqual(summary["strict"]["pairs"], 0)
        self.assertLess(summary["legacy_simulation"]["win_ci_low"], 0.5)

    def test_dashboard_uses_correct_market_labels_and_validation_contract(self):
        page = build_html(self._state())
        self.assertIn('data-testid="validation-center"', page)
        self.assertIn('data-testid="adaptive-strategy"', page)
        self.assertIn("三类证据严格隔离", page)
        self.assertIn("全市场等权涨跌", page)
        self.assertIn("视图不控制执行", page)
        self.assertIn("旧规则影子分", page)
        self.assertNotIn("上证 1日", page)

    def test_market_metrics_include_turnover_breadth_and_fresh_coverage(self):
        quotes = pd.DataFrame([
            {"code": "000001", "name": "甲", "price": 10.1, "prev_close": 10.0, "open": 10.0, "change_pct": 1.0, "amount": 100_000_000, "quote_time": "2026-08-03T14:50:10+08:00"},
            {"code": "300001", "name": "乙", "price": 9.8, "prev_close": 10.0, "open": 10.0, "change_pct": -2.0, "amount": 200_000_000, "quote_time": "2026-08-03T14:50:11+08:00"},
        ])
        with patch("v4.execution.TradingClock.quote_is_fresh", return_value=True):
            market = SimulationEngine()._get_market_state(quotes, expected_codes=2)
        self.assertTrue(market["data_valid"])
        self.assertEqual(market["observed_codes"], 2)
        self.assertEqual(market["rise_count"], 1)
        self.assertEqual(market["fall_count"], 1)
        self.assertAlmostEqual(market["market_total_amount_yi"], 3.0)
        self.assertEqual(market["fresh_quote_coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
