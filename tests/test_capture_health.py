import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from phase1.overnight.capture_health import evaluate_capture_session
from phase1.overnight.dataset import FEATURE_COLUMNS
from phase1.overnight.live_features import save_signal_features
from v4.execution import CHINA_TZ
from v4.snapshot_compat import capture_frame


class CaptureHealthTests(unittest.TestCase):
    def test_missing_capture_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = evaluate_capture_session(Path(temp_dir), "buy", "2026-08-03")
        self.assertFalse(result["passed"])

    def test_audited_order_book_snapshot_passes(self):
        now = datetime(2026, 8, 3, 14, 50, 10, tzinfo=CHINA_TZ)
        frame = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "测试",
                    "price": 10.0,
                    "ask1": 10.01,
                    "ask1_volume": 50_000,
                    "quote_time": now.isoformat(),
                }
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("v4.snapshot_compat.SNAPSHOT_ROOT", Path(temp_dir)):
                capture_frame(
                    frame,
                    "buy",
                    now=now,
                    expected_codes=["000001"],
                    require_order_book=True,
                )
            result = evaluate_capture_session(
                Path(temp_dir), "buy", "2026-08-03"
            )
        self.assertTrue(result["passed"])
        self.assertTrue(result["best"]["causal"])
        self.assertTrue(result["best"]["window_ok"])
        self.assertTrue(result["best"]["manifest_ok"])
        self.assertTrue(result["best"]["order_book_ok"])

    def test_snapshot_outside_declared_trade_date_is_rejected(self):
        now = datetime(2026, 8, 3, 14, 50, 10, tzinfo=CHINA_TZ)
        frame = pd.DataFrame([{
            "code": "000001", "price": 10.0, "ask1": 10.01,
            "ask1_volume": 50_000, "quote_time": now.isoformat(),
        }])
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("v4.snapshot_compat.SNAPSHOT_ROOT", Path(temp_dir)):
                output = capture_frame(
                    frame, "buy", now=now, expected_codes=["000001"],
                    require_order_book=True,
                )
            result = evaluate_capture_session(
                Path(temp_dir), "buy", "2026-08-04"
            )
        self.assertFalse(result["passed"])

    def test_complete_strict_signal_snapshot_passes(self):
        now = datetime(2026, 8, 3, 14, 49, 20, tzinfo=CHINA_TZ)
        row = {
            "trade_date": "2026-08-03", "code": "000001", "name": "测试",
            "quote_time": now.isoformat(), "as_of": now.isoformat(),
            "session": "signal", "feature_mode": "strict_pre_1450",
            "context_date": "2026-07-31", "window_valid": True,
            "quote_is_fresh": True, "is_mock": False,
        }
        row.update({column: 0.0 for column in FEATURE_COLUMNS})
        manifest = {
            "contract_version": "strict-signal-snapshot-v2",
            "captured_at": now.isoformat(),
            "expected_context_codes": 1,
            "strict_feature_rows": 1,
            "strict_feature_coverage": 1.0,
            "causal_quote_time_required": True,
            "expected_universe_sha256": "a" * 64,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = (
                Path(temp_dir) / "signal" / "2026-08-03_144920.csv"
            )
            save_signal_features(pd.DataFrame([row]), output, manifest)
            result = evaluate_capture_session(
                Path(temp_dir), "signal", "2026-08-03"
            )
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
