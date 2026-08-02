import tempfile
import unittest
from pathlib import Path

import pandas as pd

from phase1.overnight.dataset import FEATURE_COLUMNS
from phase1.overnight.live_features import build_symbol_context, compute_live_features


class LiveFeatureTests(unittest.TestCase):
    @staticmethod
    def _write_complete_history(path: Path):
        rows = []
        for index, day in enumerate(pd.bdate_range("2026-07-02", "2026-07-31")):
            base = 10.0 + index * 0.02
            for clock, offset in (
                ("10:30:00", 0.00),
                ("11:30:00", 0.01),
                ("14:00:00", 0.02),
                ("15:00:00", 0.03),
            ):
                price = base + offset
                rows.append(
                    {
                        "date": f"{day:%Y-%m-%d} {clock}",
                        "open": price - 0.01,
                        "high": price + 0.02,
                        "low": price - 0.02,
                        "close": price,
                        "volume": 1000 + index,
                    }
                )
        pd.DataFrame(rows).to_csv(path, index=False)

    def test_context_and_1449_quote_produce_all_strict_features(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "000001.csv"
            self._write_complete_history(path)
            row, reason = build_symbol_context(path, "2026-07-31")
            context = pd.DataFrame([row])
            quotes = pd.DataFrame(
                [
                    {
                        "code": "000001",
                        "name": "测试股票",
                        "price": row["context_prev_close"] * 1.01,
                        "prev_close": row["context_prev_close"],
                        "open": row["context_prev_close"] * 1.002,
                        "high": row["context_prev_close"] * 1.012,
                        "low": row["context_prev_close"] * 0.998,
                        "volume": row["volume_mean_20"] * 0.7,
                        "quote_time": "2026-08-03T14:49:05+08:00",
                    }
                ]
            )
            features = compute_live_features(
                quotes, context, as_of="2026-08-03T14:49:10+08:00"
            )

        self.assertEqual(reason, "ok")
        self.assertEqual(len(features), 1)
        self.assertEqual(features.iloc[0]["feature_mode"], "strict_pre_1450")
        self.assertTrue(features[FEATURE_COLUMNS].notna().all(axis=None))

    def test_quote_after_capture_time_is_rejected(self):
        context = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "context_prev_close": 10.0,
                    "context_date": "2026-07-31",
                    "volume_mean_20": 1000,
                    "ma5_base": 10,
                    "ma10_base": 10,
                    "ma20_base": 10,
                    "ret_1d": 0,
                    "ret_3d": 0,
                    "ret_5d": 0,
                    "ret_10d": 0,
                    "ret_20d": 0,
                    "volatility_20": 0.01,
                    "overnight_mean_20": 0,
                    "overnight_hit_1pct_20": 0,
                }
            ]
        )
        quotes = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "price": 10.1,
                    "prev_close": 10.0,
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "volume": 700,
                    "quote_time": "2026-08-03T14:49:11+08:00",
                }
            ]
        )
        features = compute_live_features(
            quotes, context, as_of="2026-08-03T14:49:10+08:00"
        )
        self.assertTrue(features.empty)


if __name__ == "__main__":
    unittest.main()
