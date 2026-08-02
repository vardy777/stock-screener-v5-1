import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from v4.execution import CHINA_TZ, TradingClock
from v4.readiness import ResearchReadiness
from v4.runtime import V4Runtime
from v4.snapshots import capture_frame


class V4Tests(unittest.TestCase):
    def test_scheduler_entrypoints_are_preserved(self):
        root = Path(__file__).resolve().parent.parent
        for relative in (
            "v3/scripts/afternoon_push.py",
            "v3/scripts/morning_push.py",
            "v3/scripts/watchlist_scan.py",
            "phase1/scripts/run_scheduled_capture.ps1",
            "phase1/scripts/run_scheduled_health.ps1",
            "phase1/scripts/run_scheduled_push.ps1",
            "phase1/scripts/run_dashboard_local.ps1",
            "phase1/scripts/run_daily_maintenance.ps1",
            "phase1/scripts/prepare_next_session.py",
            "phase1/scripts/test_pushplus.py",
        ):
            self.assertTrue((root / relative).exists(), relative)

    def test_clock_enforces_buy_sell_windows_and_weekends(self):
        monday_buy = datetime(2026, 8, 3, 14, 50, 30, tzinfo=CHINA_TZ)
        monday_sell = datetime(2026, 8, 3, 9, 30, 30, tzinfo=CHINA_TZ)
        saturday = datetime(2026, 8, 1, 14, 50, 30, tzinfo=CHINA_TZ)

        self.assertTrue(TradingClock.action_status("buy", now=monday_buy).allowed)
        self.assertTrue(TradingClock.action_status("sell", now=monday_sell).allowed)
        self.assertFalse(TradingClock.action_status("buy", now=saturday).allowed)
        self.assertFalse(TradingClock.action_status("sell", now=monday_buy).allowed)

    def test_clock_blocks_exchange_holiday_and_uncovered_year(self):
        holiday = datetime(2026, 10, 1, 14, 50, 30, tzinfo=CHINA_TZ)
        uncovered = datetime(2027, 1, 4, 14, 50, 30, tzinfo=CHINA_TZ)
        holiday_status = TradingClock.action_status("buy", now=holiday)
        uncovered_status = TradingClock.action_status("buy", now=uncovered)
        self.assertFalse(holiday_status.allowed)
        self.assertIn("休市", holiday_status.reason)
        self.assertFalse(uncovered_status.allowed)
        self.assertIn("交易日历", uncovered_status.reason)

    def test_current_proxy_report_keeps_v4_research_locked(self):
        readiness = ResearchReadiness().evaluate()
        self.assertFalse(readiness["trade_enabled"])
        self.assertEqual(readiness["status"], "research_locked")
        self.assertTrue(readiness["shadow_enabled"])

    def test_runtime_keeps_candidates_visible_but_non_tradable(self):
        runtime = V4Runtime()
        candidate = {
            "code": "000001",
            "name": "测试",
            "price": 10.0,
            "score": 92.0,
            "rank": 1,
            "quote_time": TradingClock.now().isoformat(),
        }
        result = runtime.evaluate_candidates(
            [candidate], {"mode_label": "neutral", "advance_ratio": 0.6}
        )
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["v4_tradable"])
        self.assertIn("研究准入未通过", result[0]["v4_block_reasons"])
        self.assertIn("v4_shadow_confidence", result[0])

    def test_snapshot_keeps_only_fresh_non_mock_rows_in_exact_window(self):
        now = datetime(2026, 8, 3, 14, 50, 30, tzinfo=CHINA_TZ)
        frame = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "正常股票",
                    "price": 10.0,
                    "quote_time": now.isoformat(),
                    "is_mock": False,
                },
                {
                    "code": "000002",
                    "name": "模拟股票",
                    "price": 11.0,
                    "quote_time": now.isoformat(),
                    "is_mock": True,
                },
                {
                    "code": "000003",
                    "name": "过期股票",
                    "price": 12.0,
                    "quote_time": "2026-08-03T14:40:00+08:00",
                    "is_mock": False,
                },
            ]
        )
        with TemporaryDirectory() as temp_dir:
            with patch("v4.snapshots.SNAPSHOT_ROOT", Path(temp_dir)):
                output = capture_frame(frame, "buy", now=now)
                self.assertIsNotNone(output)
                saved = pd.read_csv(output, dtype={"code": str})
                manifest = json.loads(
                    output.with_suffix(output.suffix + ".meta.json").read_text(
                        encoding="utf-8"
                    )
                )

        self.assertEqual(saved["code"].tolist(), ["000001"])
        self.assertTrue(saved["quote_is_fresh"].all())
        self.assertTrue(saved["window_valid"].all())
        self.assertFalse(saved["is_mock"].all())
        self.assertTrue(manifest["causal_quote_time_required"])

    def test_future_quotes_and_low_coverage_are_rejected(self):
        now = datetime(2026, 8, 3, 14, 50, 30, tzinfo=CHINA_TZ)
        self.assertFalse(
            TradingClock.quote_is_fresh((now + timedelta(seconds=1)).isoformat(), now=now)
        )
        frame = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "正常股票",
                    "price": 10.0,
                    "quote_time": now.isoformat(),
                }
            ]
        )
        with TemporaryDirectory() as temp_dir:
            with patch("v4.snapshots.SNAPSHOT_ROOT", Path(temp_dir)):
                output = capture_frame(
                    frame,
                    "buy",
                    now=now,
                    expected_codes=["000001", "000002"],
                    minimum_coverage=0.95,
                )
                self.assertIsNone(output)
                self.assertEqual(list(Path(temp_dir).rglob("*.csv")), [])

    def test_strict_buy_snapshot_uses_ask1_not_last_price(self):
        now = datetime(2026, 8, 3, 14, 50, 30, tzinfo=CHINA_TZ)
        frame = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "正常股票",
                    "price": 10.00,
                    "ask1": 10.02,
                    "ask1_volume": 20_000,
                    "bid1": 9.99,
                    "bid1_volume": 18_000,
                    "quote_time": now.isoformat(),
                }
            ]
        )
        with TemporaryDirectory() as temp_dir:
            with patch("v4.snapshots.SNAPSHOT_ROOT", Path(temp_dir)):
                output = capture_frame(
                    frame,
                    "buy",
                    now=now,
                    expected_codes=["000001"],
                    require_order_book=True,
                )
                saved = pd.read_csv(output, dtype={"code": str})
        self.assertEqual(float(saved.iloc[0]["last_price"]), 10.0)
        self.assertEqual(float(saved.iloc[0]["price"]), 10.02)
        self.assertEqual(saved.iloc[0]["execution_price_source"], "ask1")
        self.assertTrue(saved.iloc[0]["order_book_verified"])

    def test_snapshot_rejects_outside_window_and_unknown_session(self):
        outside = datetime(2026, 8, 3, 14, 49, 59, tzinfo=CHINA_TZ)
        frame = pd.DataFrame(
            [{"code": "000001", "name": "测试", "price": 10.0, "quote_time": outside.isoformat()}]
        )
        self.assertIsNone(capture_frame(frame, "buy", now=outside))
        self.assertIsNone(capture_frame(frame, "other", now=outside))


if __name__ == "__main__":
    unittest.main()
