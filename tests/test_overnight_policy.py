import unittest

import numpy as np
import pandas as pd

from phase1.overnight.backtesting import (
    SelectionPolicy,
    build_precision_coverage_report,
    calculate_metrics,
)
from phase1.overnight.dataset import FEATURE_COLUMNS
from phase1.overnight.model import LightGBMSignalModel, RidgeSignalModel


class OvernightPolicyTests(unittest.TestCase):
    def test_v4_selection_policy_cannot_expand_beyond_top1(self):
        with self.assertRaisesRegex(ValueError, "Top1"):
            SelectionPolicy(max_positions=2)

    def test_ridge_model_exposes_all_decision_targets(self):
        rng = np.random.default_rng(42)
        rows = 160
        frame = pd.DataFrame(
            {feature: rng.normal(size=rows) for feature in FEATURE_COLUMNS}
        )
        frame["net_return"] = rng.normal(0.001, 0.015, size=rows)
        frame["target_1pct"] = (frame["net_return"] >= 0.01).astype(int)
        frame["large_loss"] = (frame["net_return"] <= -0.02).astype(int)

        model = RidgeSignalModel(FEATURE_COLUMNS).fit(frame)
        predicted = model.predict(frame.head(12))

        self.assertEqual(
            set(predicted.columns),
            {
                "predicted_return",
                "predicted_positive_probability",
                "predicted_hit_probability",
                "predicted_large_loss_probability",
            },
        )
        for column in predicted.columns[1:]:
            self.assertTrue(predicted[column].between(0.0, 1.0).all())

    def test_lightgbm_handles_single_class_risk_targets(self):
        rng = np.random.default_rng(7)
        rows = 140
        frame = pd.DataFrame(
            {feature: rng.normal(size=rows) for feature in FEATURE_COLUMNS}
        )
        frame["net_return"] = np.full(rows, 0.002)
        frame["target_1pct"] = 0
        frame["large_loss"] = 0
        model = LightGBMSignalModel(FEATURE_COLUMNS).fit(frame)
        predicted = model.predict(frame.head(5))
        self.assertTrue((predicted["predicted_positive_probability"] == 1.0).all())
        self.assertTrue((predicted["predicted_hit_probability"] == 0.0).all())
        self.assertTrue((predicted["predicted_large_loss_probability"] == 0.0).all())

    def test_precision_coverage_report_separates_win_and_one_percent_hit(self):
        trades = pd.DataFrame(
            {
                "selection_score": np.linspace(0.0, 1.0, 20),
                "predicted_return": np.linspace(-0.01, 0.02, 20),
                "predicted_positive_probability": np.linspace(0.1, 0.9, 20),
                "net_return": np.linspace(-0.02, 0.03, 20),
            }
        )
        report = build_precision_coverage_report(trades)
        self.assertFalse(report.empty)
        self.assertIn("win_rate", report.columns)
        self.assertIn("target_1pct_rate", report.columns)
        self.assertTrue((report["trades"] > 0).all())

    def test_metrics_treat_any_non_strict_contract_as_proxy(self):
        trades = pd.DataFrame(
            {
                "net_return": [0.01, 0.02],
                "execution_mode": ["snapshot_14_50", "snapshot_14_50"],
                "exit_mode": ["snapshot_09_30", "snapshot_09_30"],
                "exact_buy": [True, True],
                "exact_sell": [True, True],
                "feature_mode": ["strict_pre_1450", "hourly_signal_proxy"],
                "calendar_verified": [True, True],
                "order_book_verified": [True, True],
                "order_book_liquidity_verified": [True, True],
                "exit_delay_days": [0, 0],
            }
        )
        daily = pd.DataFrame(
            {
                "positions": [1, 1],
                "end_capital": [101000.0, 103000.0],
                "daily_return": [0.01, 0.0198],
            }
        )
        metrics = calculate_metrics(trades, daily, 100000.0)
        self.assertEqual(metrics["strict_buy_trade_rate"], 1.0)
        self.assertEqual(metrics["strict_sell_trade_rate"], 1.0)
        self.assertEqual(metrics["strict_feature_trade_rate"], 0.5)
        self.assertEqual(metrics["order_book_verified_trade_rate"], 1.0)
        self.assertEqual(metrics["order_book_liquidity_trade_rate"], 1.0)
        self.assertEqual(metrics["strict_trade_rate"], 0.5)
        self.assertEqual(metrics["proxy_trade_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
