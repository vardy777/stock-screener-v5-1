import unittest

import pandas as pd

from v4.selection import V4CandidateSelector


class ConfirmationScoringTests(unittest.TestCase):
    @staticmethod
    def morning(code, base_score, signal=0.02, close=0.7, volume=1.0):
        return {
            "code": code, "base_score": base_score, "score": base_score,
            "strategy_key": "momentum", "strategy": "V4强势延续",
            "v4_features": {
                "signal_return": signal,
                "signal_close_position": close,
                "volume_ratio_20": volume,
            },
        }

    def test_small_pool_does_not_recompute_percentile_rank(self):
        frame = pd.DataFrame([
            {"code": "000001", "signal_return": 0.02,
             "signal_close_position": 0.7, "volume_ratio_20": 1.0},
            {"code": "000002", "signal_return": 0.02,
             "signal_close_position": 0.7, "volume_ratio_20": 1.0},
        ])
        result = V4CandidateSelector._apply_confirmation_score(
            frame,
            [self.morning("000001", 90), self.morning("000002", 70)],
        ).set_index("code")
        self.assertEqual(float(result.loc["000001", "base_score"]), 90.0)
        self.assertEqual(float(result.loc["000002", "base_score"]), 70.0)
        self.assertEqual(float(result.loc["000001", "confirm_delta"]), 0.0)
        self.assertEqual(float(result.loc["000002", "confirm_delta"]), 0.0)
        self.assertGreater(
            float(result.loc["000001", "decision_score"]),
            float(result.loc["000002", "decision_score"]),
        )

    def test_confirmation_delta_is_fixed_bounded_and_causal(self):
        frame = pd.DataFrame([{
            "code": "000001", "signal_return": 0.20,
            "signal_close_position": 1.0, "volume_ratio_20": 10.0,
        }])
        result = V4CandidateSelector._apply_confirmation_score(
            frame, [self.morning("000001", 75)]
        ).iloc[0]
        self.assertEqual(float(result["confirm_delta"]), 5.0)
        self.assertEqual(float(result["decision_score"]), 80.0)

    def test_symbol_without_frozen_morning_score_is_excluded(self):
        frame = pd.DataFrame([{
            "code": "000002", "signal_return": 0.02,
            "signal_close_position": 0.7, "volume_ratio_20": 1.0,
        }])
        result = V4CandidateSelector._apply_confirmation_score(
            frame, [self.morning("000001", 80)]
        )
        self.assertTrue(result.empty)


if __name__ == "__main__":
    unittest.main()
