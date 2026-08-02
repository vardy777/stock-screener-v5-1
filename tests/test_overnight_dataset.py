import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from phase1.overnight.dataset import build_symbol_frame


class OvernightDatasetTests(unittest.TestCase):
    def _write_hourly_fixture(self, path: Path):
        rows = []
        start = datetime(2025, 1, 2)
        price = 10.0
        for offset in range(70):
            day = start + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            day_open = price * 1.001
            bar_open = day_open
            for clock, drift in [("10:30", 0.001), ("11:30", 0.001), ("14:00", 0.001), ("15:00", 0.001)]:
                bar_close = bar_open * (1 + drift)
                rows.append(
                    {
                        "date": f"{day:%Y-%m-%d} {clock}:00",
                        "open": bar_open,
                        "high": max(bar_open, bar_close) * 1.001,
                        "low": min(bar_open, bar_close) * 0.999,
                        "close": bar_close,
                        "volume": 1_000_000,
                    }
                )
                bar_open = bar_close
            price = bar_close
        pd.DataFrame(rows).to_csv(path, index=False)

    def test_hourly_archive_is_explicitly_marked_as_proxy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "000001.csv"
            self._write_hourly_fixture(path)
            result = build_symbol_frame(path)
            self.assertFalse(result.empty)
            self.assertEqual(set(result["execution_mode"]), {"close_proxy_15_00"})
            self.assertTrue((result["proxy_minutes"] == 10).all())
            self.assertTrue(result["net_return"].notna().all())
            self.assertTrue((result["shares_at_100k"] % 100 == 0).all())


if __name__ == "__main__":
    unittest.main()
