import unittest
from datetime import datetime, timedelta

import pandas as pd

from v4.execution import CHINA_TZ
from v4.market_contracts import ContractViolation, MarketSnapshotV1
from v4.market_gateway import MarketDataGateway


class Provider:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def batch_fetch_quotes(self, codes):
        self.calls.append(codes)
        return self.frame


class MarketGatewayTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 3, 14, 49, 10, tzinfo=CHINA_TZ)

    def frame(self):
        quote_time = self.now - timedelta(seconds=1)
        frame = pd.DataFrame([{
            "code": "000001", "name": "平安银行", "trade_date": "2026-08-03",
            "exchange_time": quote_time.isoformat(), "provider_time": quote_time.isoformat(),
            "received_at": self.now.isoformat(), "price": 10.0, "prev_close": 9.9,
            "bid1": 9.99, "bid1_volume": 100, "ask1": 10.01,
            "ask1_volume": 100, "volume": 1000, "amount": 10000.0,
            "halted": False, "limit_up": False, "limit_down": False,
            "provider": "test", "is_mock": False,
        }])
        frame.attrs["batch_started_at"] = (self.now - timedelta(seconds=2)).isoformat()
        frame.attrs["batch_completed_at"] = self.now.isoformat()
        return frame

    def test_gateway_is_provider_boundary_and_returns_snapshot(self):
        provider = Provider(self.frame())
        snapshot = MarketDataGateway(provider).fetch_snapshot(
            ["000001"], session="signal", now=self.now, require_order_book=False
        )
        self.assertIsInstance(snapshot, MarketSnapshotV1)
        self.assertEqual(provider.calls, [["000001"]])
        self.assertTrue(snapshot.quality.accepted)
        self.assertEqual(snapshot.quotes[0].code, "000001")

    def test_gateway_rejects_naive_capture_time(self):
        with self.assertRaisesRegex(ContractViolation, "timezone is required"):
            MarketDataGateway(Provider(self.frame())).fetch_snapshot(
                ["000001"], session="signal", now=datetime(2026, 8, 3, 14, 49)
            )
