import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from phase1.overnight.dataset import FEATURE_COLUMNS
from phase1.overnight.execution_labels import (
    build_execution_labels,
    save_execution_labels,
)
from v4.readiness import ResearchReadiness


class ExecutionLabelTests(unittest.TestCase):
    @staticmethod
    def _write_snapshot(
        root: Path,
        session: str,
        day: str,
        clock: str,
        price: float,
        prev_close: float,
        queue_volume: int = 1_000_000,
    ):
        directory = root / session
        directory.mkdir(parents=True, exist_ok=True)
        captured = f"{day}T{clock}+08:00"
        pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "测试股票",
                    "price": price,
                    "prev_close": prev_close,
                    "quote_time": captured,
                    "captured_at": captured,
                    "session": session,
                    "is_mock": False,
                    "quote_is_fresh": True,
                    "window_valid": True,
                    "execution_price_source": "ask1" if session == "buy" else "bid1",
                    "execution_queue_volume": queue_volume,
                }
            ]
        ).to_csv(directory / f"{day}_{clock.replace(':', '')}.csv", index=False)

    def test_pairs_next_verified_session_and_calculates_net_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "snapshots"
            self._write_snapshot(root, "buy", "2026-08-03", "14:50:10", 10.0, 9.8)
            self._write_snapshot(root, "sell", "2026-08-04", "09:30:10", 10.2, 10.0)
            calendar = Path(temp_dir) / "calendar.csv"
            pd.DataFrame(
                {
                    "date": ["2026-08-03", "2026-08-04"],
                    "is_open": [1, 1],
                    "source_url": ["https://www.sse.com.cn/official"] * 2,
                    "verified_at": ["2026-08-01"] * 2,
                }
            ).to_csv(calendar, index=False)

            labels, metadata = build_execution_labels(
                root,
                universe_codes=["000001", "000002"],
                calendar_path=calendar,
            )
            output = Path(temp_dir) / "labels.csv.gz"
            save_execution_labels(labels, metadata, output)
            loaded = pd.read_csv(output, compression="gzip", dtype={"code": str})

        self.assertEqual(len(labels), 1)
        self.assertEqual(loaded["code"].tolist(), ["000001"])
        self.assertTrue(labels.iloc[0]["valid_label"])
        self.assertGreater(labels.iloc[0]["net_return"], 0)
        self.assertTrue(metadata["calendar_verified"])
        self.assertEqual(metadata["minimum_buy_universe_coverage"], 0.5)
        self.assertEqual(metadata["strict_feature_rate"], 0.0)
        self.assertFalse(metadata["strict_dataset_ready"])

    def test_observed_sessions_never_claim_verified_calendar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "snapshots"
            self._write_snapshot(root, "buy", "2026-08-03", "14:50:10", 10.0, 9.8)
            self._write_snapshot(root, "sell", "2026-08-04", "09:30:10", 10.2, 10.0)
            labels, metadata = build_execution_labels(
                root, universe_codes=["000001"]
            )

        self.assertEqual(len(labels), 1)
        self.assertFalse(metadata["calendar_verified"])
        self.assertFalse(labels.iloc[0]["calendar_verified"])

    def test_future_dated_execution_quote_is_never_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "snapshots"
            self._write_snapshot(root, "buy", "2026-08-03", "14:50:10", 10.0, 9.8)
            self._write_snapshot(root, "sell", "2026-08-04", "09:30:10", 10.2, 10.0)
            buy_path = next((root / "buy").glob("*.csv"))
            buy = pd.read_csv(buy_path, dtype={"code": str})
            buy.loc[0, "quote_time"] = "2026-08-03T14:50:11+08:00"
            buy.to_csv(buy_path, index=False)
            labels, metadata = build_execution_labels(
                root, universe_codes=["000001"]
            )

        self.assertTrue(labels.empty)
        self.assertEqual(metadata["buy"]["valid_rows"], 0)

    def test_strict_signal_features_complete_the_auditable_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "snapshots"
            self._write_snapshot(root, "buy", "2026-08-03", "14:50:10", 10.0, 9.8)
            self._write_snapshot(root, "sell", "2026-08-04", "09:30:10", 10.2, 10.0)
            signal_dir = root / "signal"
            signal_dir.mkdir(parents=True)
            signal = {
                "trade_date": "2026-08-03",
                "code": "000001",
                "name": "测试股票",
                "quote_time": "2026-08-03T14:49:05+08:00",
                "as_of": "2026-08-03T14:49:10+08:00",
                "session": "signal",
                "feature_mode": "strict_pre_1450",
                "context_date": "2026-07-31",
                "window_valid": True,
                "quote_is_fresh": True,
                "is_mock": False,
            }
            signal.update({column: 0.1 for column in FEATURE_COLUMNS})
            pd.DataFrame([signal]).to_csv(signal_dir / "2026-08-03.csv", index=False)
            calendar = Path(temp_dir) / "calendar.csv"
            pd.DataFrame(
                {
                    "date": ["2026-08-03", "2026-08-04"],
                    "is_open": [1, 1],
                    "source_url": ["https://www.sse.com.cn/official"] * 2,
                    "verified_at": ["2026-08-01"] * 2,
                }
            ).to_csv(calendar, index=False)

            labels, metadata = build_execution_labels(
                root,
                universe_codes=["000001"],
                calendar_path=calendar,
            )

        self.assertEqual(len(labels), 1)
        self.assertTrue(labels.iloc[0]["strict_feature"])
        self.assertEqual(labels.iloc[0]["feature_mode"], "strict_pre_1450")
        self.assertEqual(metadata["strict_feature_rate"], 1.0)
        self.assertEqual(metadata["order_book_verified_rate"], 1.0)
        self.assertEqual(metadata["order_book_liquidity_rate"], 1.0)
        self.assertTrue(metadata["strict_dataset_ready"])

    def test_insufficient_level1_liquidity_invalidates_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "snapshots"
            self._write_snapshot(
                root, "buy", "2026-08-03", "14:50:10", 10.0, 9.8,
                queue_volume=100,
            )
            self._write_snapshot(
                root, "sell", "2026-08-04", "09:30:10", 10.2, 10.0,
                queue_volume=100,
            )
            calendar = Path(temp_dir) / "calendar.csv"
            pd.DataFrame(
                {
                    "date": ["2026-08-03", "2026-08-04"],
                    "is_open": [1, 1],
                    "source_url": ["https://www.sse.com.cn/official"] * 2,
                    "verified_at": ["2026-08-01"] * 2,
                }
            ).to_csv(calendar, index=False)
            labels, metadata = build_execution_labels(
                root, universe_codes=["000001"], calendar_path=calendar
            )

        self.assertEqual(len(labels), 1)
        self.assertFalse(labels.iloc[0]["order_book_liquidity_verified"])
        self.assertEqual(int(labels.iloc[0]["valid_label"]), 0)
        self.assertEqual(metadata["order_book_liquidity_rate"], 0.0)
        self.assertFalse(metadata["strict_dataset_ready"])


class HardenedReadinessTests(unittest.TestCase):
    @staticmethod
    def _summary(**overrides):
        value = {
            "trades": 500,
            "strict_1450_rows": 500,
            "win_rate_ci_low_95": 0.51,
            "profit_factor": 1.25,
            "window_consistency": 0.75,
            "max_drawdown": -0.08,
            "cumulative_return": 0.10,
            "acceptance_pass": True,
            "proxy_trade_rate": 0.0,
            "strict_buy_trade_rate": 1.0,
            "strict_sell_trade_rate": 1.0,
            "strict_feature_trade_rate": 1.0,
            "strict_trade_rate": 1.0,
            "calendar_verified_trade_rate": 1.0,
            "order_book_verified_trade_rate": 1.0,
            "order_book_liquidity_trade_rate": 1.0,
            "calendar_verified": True,
            "minimum_buy_universe_coverage": 0.95,
            "volume_unit_verified": True,
        }
        value.update(overrides)
        return value

    @staticmethod
    def _write_json(path: Path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_all_strict_contracts_are_required_for_paper_ready(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_json(root / "wf_report" / "summary.json", self._summary())
            self._write_json(
                root / "wf_report_stress" / "summary.json", self._summary()
            )
            self._write_json(
                root / "model" / "training_info.json",
                {"model": "ridge", "research_only": False},
            )
            self._write_json(root / "model" / "overnight_ridge.json", {"ok": True})
            with patch("v4.readiness.OVERNIGHT", root):
                ready = ResearchReadiness().evaluate()

            self._write_json(
                root / "wf_report" / "summary.json",
                self._summary(strict_feature_trade_rate=0.99),
            )
            with patch("v4.readiness.OVERNIGHT", root):
                blocked = ResearchReadiness().evaluate()

        self.assertEqual(ready["status"], "paper_ready")
        self.assertTrue(ready["trade_enabled"])
        self.assertFalse(blocked["trade_enabled"])
        self.assertFalse(
            next(
                item for item in blocked["checks"] if item["key"] == "strict_features"
            )["passed"]
        )


if __name__ == "__main__":
    unittest.main()
