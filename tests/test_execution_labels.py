import hashlib
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
    def _write_calendar(path: Path):
        days = pd.date_range("2026-01-01", "2026-12-31", freq="D")
        pd.DataFrame(
            {
                "date": days.strftime("%Y-%m-%d"),
                "is_open": [int(day.weekday() < 5) for day in days],
                "source_url": ["https://www.sse.com.cn/official"] * len(days),
                "verified_at": ["2026-08-01"] * len(days),
            }
        ).to_csv(path, index=False)

    @staticmethod
    def _write_snapshot(
        root: Path,
        session: str,
        day: str,
        clock: str,
        price: float,
        prev_close: float,
        queue_volume: int = 1_000_000,
        capture_role: str = "strict_probe",
    ):
        directory = root / session
        directory.mkdir(parents=True, exist_ok=True)
        captured = f"{day}T{clock}+08:00"
        snapshot_path = directory / f"{day}_{clock.replace(':', '')}.csv"
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
                    "capture_role": capture_role,
                }
            ]
        ).to_csv(snapshot_path, index=False)
        manifest = {
            "contract_version": "strict-execution-snapshot-v2",
            "session": session,
            "captured_at": captured,
            "data_file": snapshot_path.name,
            "data_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
            "expected_codes": 1,
            "expected_universe_sha256": hashlib.sha256(b"000001").hexdigest(),
            "valid_rows": 1,
            "coverage": 1.0,
            "minimum_coverage": 0.95,
            "causal_quote_time_required": True,
            "order_book_required": True,
            "order_book_verified_rows": 1,
            "window_valid": True,
            "capture_role": capture_role,
        }
        snapshot_path.with_suffix(snapshot_path.suffix + ".meta.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def test_pairs_next_verified_session_and_calculates_net_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "snapshots"
            self._write_snapshot(root, "buy", "2026-08-03", "14:50:10", 10.0, 9.8)
            self._write_snapshot(root, "sell", "2026-08-04", "09:30:10", 10.2, 10.0)
            calendar = Path(temp_dir) / "calendar.csv"
            self._write_calendar(calendar)

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
        self.assertEqual(metadata["minimum_buy_universe_coverage"], 1.0)
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

    def test_buy_label_prefers_the_actual_confirmation_quote(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "snapshots"
            self._write_snapshot(
                root, "buy", "2026-08-03", "14:50:01", 10.0, 9.8,
                capture_role="scheduled_probe",
            )
            self._write_snapshot(
                root, "buy", "2026-08-03", "14:50:20", 10.1, 9.8,
                capture_role="decision_confirmation",
            )
            self._write_snapshot(root, "sell", "2026-08-04", "09:30:10", 10.2, 10.1)
            labels, _ = build_execution_labels(root, universe_codes=["000001"])

        self.assertEqual(len(labels), 1)
        self.assertAlmostEqual(float(labels.iloc[0]["buy_reference"]), 10.1)
        self.assertEqual(labels.iloc[0]["capture_role_buy"], "decision_confirmation")

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
            signal_path = signal_dir / "2026-08-03.csv"
            pd.DataFrame([signal]).to_csv(signal_path, index=False)
            signal_path.with_suffix(signal_path.suffix + ".meta.json").write_text(
                json.dumps(
                    {
                        "contract_version": "strict-signal-snapshot-v2",
                        "captured_at": "2026-08-03T14:49:10+08:00",
                        "data_file": signal_path.name,
                        "data_sha256": hashlib.sha256(signal_path.read_bytes()).hexdigest(),
                        "expected_context_codes": 1,
                        "expected_universe_sha256": hashlib.sha256(b"000001").hexdigest(),
                        "strict_feature_rows": 1,
                        "strict_feature_coverage": 1.0,
                        "minimum_coverage": 0.95,
                        "causal_quote_time_required": True,
                    }
                ),
                encoding="utf-8",
            )
            calendar = Path(temp_dir) / "calendar.csv"
            self._write_calendar(calendar)

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
            self._write_calendar(calendar)
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
            "point_in_time_universe_verified": True,
            "point_in_time_security_name_verified": True,
            "dataset_mode": "strict",
            "lineage_verified": True,
            "dataset_sha256": "d" * 64,
            "stress_policy_frozen": True,
            "total_windows": 4,
            "frozen_policy_windows": 4,
        }
        value.update(overrides)
        return value

    @staticmethod
    def _write_json(path: Path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_release(self, root: Path):
        model_dir = root / "model"
        schema_hash = hashlib.sha256(
            json.dumps(FEATURE_COLUMNS, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        width = len(FEATURE_COLUMNS)
        model = {
            "feature_columns": FEATURE_COLUMNS,
            "medians": [0.0] * width,
            "means": [0.0] * width,
            "scales": [1.0] * width,
            "return_coef": [0.0] * (width + 1),
            "positive_coef": [0.0] * (width + 1),
            "hit_coef": [0.0] * (width + 1),
            "loss_coef": [0.0] * (width + 1),
        }
        policy = {
            "contract_version": "v4-selection-policy-v1",
            "feature_columns": FEATURE_COLUMNS,
            "max_positions": 1,
            "minimum_predicted_return": 0.0,
            "minimum_positive_probability": None,
            "maximum_large_loss_probability": None,
            "minimum_regime_score": None,
            "score_column": "predicted_return",
        }
        training = {
            "model": "ridge",
            "research_only": False,
            "dataset_mode": "strict",
            "strict_dataset_ready": True,
            "point_in_time_universe_verified": True,
            "point_in_time_security_name_verified": True,
            "feature_columns": FEATURE_COLUMNS,
            "feature_schema_sha256": schema_hash,
            "dataset_sha256": "d" * 64,
            "normal_report_sha256": self._sha256(
                root / "wf_report_strict" / "summary.json"
            ),
            "stress_report_sha256": self._sha256(
                root / "wf_report_strict_stress" / "summary.json"
            ),
        }
        model_path = model_dir / "overnight_ridge.json"
        policy_path = model_dir / "selection_policy.json"
        training_path = model_dir / "training_info.json"
        self._write_json(model_path, model)
        self._write_json(policy_path, policy)
        self._write_json(training_path, training)
        self._write_json(
            model_dir / "published_model.json",
            {
                "contract_version": "v4-published-model-v1",
                "model_file": model_path.name,
                "model_sha256": self._sha256(model_path),
                "policy_file": policy_path.name,
                "policy_sha256": self._sha256(policy_path),
                "training_info_file": training_path.name,
                "training_info_sha256": self._sha256(training_path),
                "dataset_sha256": "d" * 64,
                "feature_schema_sha256": schema_hash,
            },
        )

    def test_all_strict_contracts_are_required_for_paper_ready(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            window_path = root / "wf_report_strict" / "window_stats.csv"
            window_path.parent.mkdir(parents=True, exist_ok=True)
            window_path.write_text("test_start,policy_score_column\n2026-01-01,predicted_return\n", encoding="utf-8")
            window_hash = self._sha256(window_path)
            self._write_json(
                root / "wf_report_strict" / "summary.json",
                self._summary(window_stats_sha256=window_hash),
            )
            normal_hash = self._sha256(
                root / "wf_report_strict" / "summary.json"
            )
            self._write_json(
                root / "wf_report_strict_stress" / "summary.json",
                self._summary(
                    normal_report_sha256=normal_hash,
                    normal_window_stats_sha256=window_hash,
                ),
            )
            self._write_release(root)
            with patch("v4.readiness.OVERNIGHT", root):
                ready = ResearchReadiness().evaluate()

            self._write_json(
                root / "wf_report_strict" / "summary.json",
                self._summary(
                    strict_feature_trade_rate=0.99,
                    window_stats_sha256=window_hash,
                ),
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
