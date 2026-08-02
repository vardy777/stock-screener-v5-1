import unittest

from strategy_spec import DEFAULT_SPEC, TradeCostModel


class TradeCostModelTests(unittest.TestCase):
    def setUp(self):
        self.model = TradeCostModel(DEFAULT_SPEC)

    def test_position_respects_one_third_all_in_cap(self):
        budget = DEFAULT_SPEC.position_budget(100_000)
        shares = self.model.max_affordable_shares(10.0, budget)
        fill = self.model.buy_fill_price(10.0)
        cash = self.model.buy_cash_required(fill, shares)
        self.assertEqual(shares % 100, 0)
        self.assertLessEqual(cash["cash_out"], budget)
        next_lot = self.model.buy_cash_required(fill, shares + 100)
        self.assertGreater(next_lot["cash_out"], budget)

    def test_flat_price_is_negative_after_costs(self):
        result = self.model.round_trip(10.0, 10.0, 3000)
        self.assertLess(result["net_return"], 0)
        self.assertGreater(result["total_fees"], 0)

    def test_required_reference_delivers_one_percent_net(self):
        budget = DEFAULT_SPEC.position_budget(100_000)
        shares = self.model.max_affordable_shares(10.0, budget)
        reference = self.model.required_sell_reference(10.0, shares)
        result = self.model.round_trip(10.0, reference, shares)
        self.assertAlmostEqual(result["net_return"], 0.01, places=9)
        self.assertEqual(result["target_1pct"], 1)

    def test_strategy_spec_matches_full_buy_window(self):
        self.assertEqual(DEFAULT_SPEC.buy_start, "14:50:00")
        self.assertEqual(DEFAULT_SPEC.buy_end, "14:51:59")


if __name__ == "__main__":
    unittest.main()
