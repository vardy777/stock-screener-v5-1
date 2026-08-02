import unittest
from datetime import datetime

import pandas as pd

from phase1.overnight.quote_capture import fetch_quotes_with_retries
from v4.execution import CHINA_TZ


class _Fetcher:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def batch_fetch_quotes(self, codes):
        self.requests.append(list(codes))
        return self.responses.pop(0) if self.responses else None


class QuoteCaptureTests(unittest.TestCase):
    def test_retries_only_missing_codes_inside_window(self):
        now = datetime(2026, 8, 3, 14, 50, 10, tzinfo=CHINA_TZ)
        fetcher = _Fetcher(
            [
                pd.DataFrame([{"code": "000001", "price": 10.0}]),
                pd.DataFrame([{"code": "000002", "price": 11.0}]),
            ]
        )
        quotes, report = fetch_quotes_with_retries(
            fetcher,
            ["000001", "000002"],
            "buy",
            minimum_coverage=1.0,
            now_fn=lambda: now,
            sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(quotes["code"].tolist(), ["000001", "000002"])
        self.assertEqual(fetcher.requests[1], ["000002"])
        self.assertEqual(report["attempt_count"], 2)
        self.assertEqual(report["quote_coverage"], 1.0)

    def test_never_calls_data_source_outside_window(self):
        sunday = datetime(2026, 8, 2, 14, 50, 10, tzinfo=CHINA_TZ)
        fetcher = _Fetcher([])
        quotes, report = fetch_quotes_with_retries(
            fetcher, ["000001"], "buy", now_fn=lambda: sunday
        )
        self.assertTrue(quotes.empty)
        self.assertEqual(fetcher.requests, [])
        self.assertFalse(report["window_allowed_at_end"])

    def test_diagnostic_mode_can_measure_source_without_claiming_window(self):
        sunday = datetime(2026, 8, 2, 14, 50, 10, tzinfo=CHINA_TZ)
        fetcher = _Fetcher([pd.DataFrame([{"code": "000001", "price": 10.0}])])
        quotes, report = fetch_quotes_with_retries(
            fetcher,
            ["000001"],
            "buy",
            require_window=False,
            now_fn=lambda: sunday,
        )
        self.assertEqual(len(quotes), 1)
        self.assertFalse(report["window_required"])
        self.assertFalse(report["window_allowed_at_end"])


if __name__ == "__main__":
    unittest.main()
