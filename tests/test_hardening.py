import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from phase1.overnight.dataset import FEATURE_COLUMNS, load_or_build_dataset
from phase1.overnight.backtesting import fit_final_model_and_policy
from trading_calendar_contract import validate_calendar_records
from v4.execution import CHINA_TZ
from v4.feature_store import LiveFeatureStore
from v4.model_registry import PublishedModelRegistry
from v4.runtime import V4Runtime
from v3.simulation import SimulationEngine


class PublishedArtifactTests(unittest.TestCase):
    @staticmethod
    def _write_json(path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _release(self, root: Path) -> Path:
        width = len(FEATURE_COLUMNS)
        schema_hash = hashlib.sha256(
            json.dumps(FEATURE_COLUMNS, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        model_path = root / "overnight_ridge.json"
        policy_path = root / "selection_policy.json"
        training_path = root / "training_info.json"
        self._write_json(
            model_path,
            {
                "feature_columns": FEATURE_COLUMNS,
                "medians": [0.0] * width,
                "means": [0.0] * width,
                "scales": [1.0] * width,
                "return_coef": [0.0] * (width + 1),
                "positive_coef": [0.0] * (width + 1),
                "hit_coef": [0.0] * (width + 1),
                "loss_coef": [0.0] * (width + 1),
            },
        )
        self._write_json(
            policy_path,
            {
                "contract_version": "v4-selection-policy-v1",
                "feature_columns": FEATURE_COLUMNS,
                "max_positions": 1,
                "minimum_predicted_return": 0.0,
                "minimum_positive_probability": None,
                "maximum_large_loss_probability": None,
                "minimum_regime_score": None,
                "score_column": "predicted_return",
            },
        )
        self._write_json(
            training_path,
            {
                "model": "ridge",
                "research_only": False,
                "dataset_mode": "strict",
                "strict_dataset_ready": True,
                "point_in_time_universe_verified": True,
                "point_in_time_security_name_verified": True,
                "feature_columns": FEATURE_COLUMNS,
                "feature_schema_sha256": schema_hash,
                "dataset_sha256": "d" * 64,
            },
        )
        self._write_json(
            root / "published_model.json",
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
        return model_path

    def test_registry_refuses_artifact_modified_after_publication(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path = self._release(root)
            self.assertTrue(PublishedModelRegistry(root).available)
            model_path.write_text("{}", encoding="utf-8")
            tampered = PublishedModelRegistry(root)
        self.assertFalse(tampered.available)
        self.assertIn("哈希", tampered.error)

    def test_registry_refuses_manifest_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_json(
                root / "published_model.json",
                {
                    "contract_version": "v4-published-model-v1",
                    "model_file": "..\\outside.pkl",
                },
            )
            registry = PublishedModelRegistry(root)
        self.assertFalse(registry.available)
        self.assertIn("不安全", registry.error)


class CausalityAndDatasetTests(unittest.TestCase):
    def test_calendar_rejects_lookalike_host_and_partial_year(self):
        base = {
            "date": "2026-08-03",
            "is_open": 1,
            "verified_at": "2026-08-01",
        }
        lookalike, _, _ = validate_calendar_records(
            [{**base, "source_url": "https://www.sse.com.cn.evil.example/x"}],
            require_complete_year=False,
        )
        partial, _, _ = validate_calendar_records(
            [{**base, "source_url": "https://www.sse.com.cn/official"}]
        )
        self.assertFalse(lookalike)
        self.assertFalse(partial)

    def test_future_live_feature_store_is_rejected(self):
        now = datetime(2026, 8, 3, 14, 49, 20, tzinfo=CHINA_TZ)
        rows = {"000001": {name: 0.0 for name in FEATURE_COLUMNS}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "live_features.json"
            with patch("v4.feature_store.STORE_PATH", path):
                LiveFeatureStore.publish(rows, as_of=now + timedelta(seconds=1))
                loaded = LiveFeatureStore.load_all(now=now)
        self.assertEqual(loaded, {})

    def test_label_unaware_rebuild_is_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(RuntimeError, "禁止无标签重建"):
                load_or_build_dataset(
                    root / "daily", root / "dataset.csv.gz", rebuild=True
                )

    def test_production_training_refuses_missing_control_columns(self):
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=90, freq="D"),
                "code": ["000001"] * 90,
                "net_return": [0.01] * 90,
            }
        )
        with self.assertRaisesRegex(ValueError, "控制列"):
            fit_final_model_and_policy(frame, model_kind="ridge")


class FullUniverseRuntimeTests(unittest.TestCase):
    class _Registry:
        available = True
        error = ""
        last_prediction_error = ""
        policy = {
            "score_column": "predicted_return",
            "minimum_predicted_return": -1.0,
            "minimum_positive_probability": 0.0,
            "maximum_large_loss_probability": 1.0,
            "minimum_regime_score": -1.0,
        }

        @staticmethod
        def _result(frame):
            score = pd.to_numeric(frame["signal_return"], errors="coerce")
            return pd.DataFrame(
                {
                    "predicted_return": score,
                    "predicted_positive_probability": 0.50 + score,
                    "predicted_hit_probability": 0.25 + score,
                    "predicted_large_loss_probability": 0.10 - score,
                },
                index=frame.index,
            )

        def predict_frame(self, frame):
            return self._result(frame)

        def predict(self, features):
            result = self._result(pd.DataFrame([features]))
            return {key: float(value) for key, value in result.iloc[0].items()}

    @staticmethod
    def _runtime():
        runtime = V4Runtime.__new__(V4Runtime)
        runtime.readiness = {"trade_enabled": True, "status": "paper_ready"}
        runtime.model_registry = FullUniverseRuntimeTests._Registry()
        return runtime

    def test_model_can_select_symbol_outside_legacy_fallback_top5(self):
        now = datetime(2026, 8, 3, 14, 50, 30, tzinfo=CHINA_TZ).isoformat()
        quotes = pd.DataFrame(
            [
                {
                    "code": f"00000{number}",
                    "name": f"股票{number}",
                    "price": 10.0,
                    "ask1": 10.01,
                    "quote_time": now,
                }
                for number in range(1, 7)
            ]
        )
        features = {}
        for number in range(1, 7):
            vector = {name: 0.0 for name in FEATURE_COLUMNS}
            vector["signal_return"] = number / 1000.0
            features[f"00000{number}"] = vector
        fallback = [{"code": f"00000{number}"} for number in range(1, 6)]
        allowed = SimpleNamespace(allowed=True, reason="", to_dict=lambda: {})
        with (
            patch("v4.runtime.LiveFeatureStore.load_all", return_value=features),
            patch("v4.runtime.TradingClock.action_status", return_value=allowed),
            patch("v4.runtime.TradingClock.quote_is_fresh", return_value=True),
            patch("v4.runtime.save_runtime_state"),
        ):
            result = self._runtime().evaluate_universe(
                quotes,
                fallback_candidates=fallback,
                market_state={"mode_label": "neutral", "data_valid": True},
            )
        self.assertEqual(result[0]["code"], "000006")
        self.assertTrue(result[0]["v4_model_ranked"])
        self.assertTrue(result[0]["v4_tradable"])

    def test_invalid_full_market_state_blocks_production_candidate(self):
        vector = {name: 0.0 for name in FEATURE_COLUMNS}
        candidate = {
            "code": "000001",
            "name": "测试",
            "price": 10.0,
            "quote_time": "2026-08-03T14:50:30+08:00",
            "rank": 1,
            "v4_features": vector,
        }
        allowed = SimpleNamespace(allowed=True, reason="", to_dict=lambda: {})
        with (
            patch("v4.runtime.TradingClock.action_status", return_value=allowed),
            patch("v4.runtime.TradingClock.quote_is_fresh", return_value=True),
            patch("v4.runtime.save_runtime_state"),
        ):
            result = self._runtime().evaluate_candidates(
                [candidate], {"mode_label": "neutral", "data_valid": False}
            )
        self.assertFalse(result[0]["v4_tradable"])
        self.assertIn("全市场状态数据无效或覆盖不足", result[0]["v4_block_reasons"])

    def test_market_coverage_deduplicates_codes_and_requires_fresh_metrics(self):
        quotes = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "price": 10.0,
                    "change_pct": 1.0,
                    "prev_close": 9.9,
                    "open": 10.0,
                    "quote_time": "2026-08-03T14:50:10+08:00",
                },
                {
                    "code": "000001",
                    "price": 10.1,
                    "change_pct": 1.2,
                    "prev_close": 9.9,
                    "open": 10.0,
                    "quote_time": "2026-08-03T14:50:11+08:00",
                },
            ]
        )
        engine = SimulationEngine()
        with patch(
            "v4.execution.TradingClock.quote_is_fresh", return_value=True
        ):
            state = engine._get_market_state(quotes, expected_codes=2)
        self.assertEqual(state["quote_coverage"], 0.5)
        self.assertFalse(state["data_valid"])


if __name__ == "__main__":
    unittest.main()
