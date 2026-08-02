"""Load only research-approved V4 model artifacts and score live feature rows."""

from __future__ import annotations

import json
import hashlib
import math
import pickle
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from phase1.overnight.dataset import FEATURE_COLUMNS


ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "phase1" / "data" / "overnight" / "model"


class PublishedModelRegistry:
    """Small production boundary around model deserialisation and schemas."""

    def __init__(self, model_dir: Optional[Path] = None):
        self.model_dir = Path(model_dir) if model_dir else MODEL_DIR
        self.manifest = self._load_json(self.model_dir / "published_model.json")
        self.info: Dict[str, Any] = {}
        self.policy: Dict[str, Any] = {}
        self.kind = ""
        self.model = None
        self.payload: Dict[str, Any] = {}
        self.error = ""
        self.last_prediction_error = ""
        if self.manifest.get("contract_version") != "v4-published-model-v1":
            self.error = "没有有效的生产模型发布清单"
            return
        training_path = self._artifact_path(
            self.manifest.get("training_info_file", "training_info.json")
        )
        policy_path = self._artifact_path(
            self.manifest.get("policy_file", "selection_policy.json")
        )
        model_path = self._artifact_path(self.manifest.get("model_file", ""))
        if training_path is None or policy_path is None or model_path is None:
            self.error = "发布清单包含不安全的产物路径"
            return
        if not self._matches_hash(
            training_path, self.manifest.get("training_info_sha256")
        ):
            self.error = "训练说明哈希不匹配"
            return
        if not self._matches_hash(policy_path, self.manifest.get("policy_sha256")):
            self.error = "生产选择策略哈希不匹配"
            return
        if not self._matches_hash(model_path, self.manifest.get("model_sha256")):
            self.error = "生产模型文件哈希不匹配"
            return
        self.info = self._load_json(training_path)
        self.policy = self._load_json(policy_path)
        self.kind = str(self.info.get("model", ""))
        schema_hash = hashlib.sha256(
            json.dumps(FEATURE_COLUMNS, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if (
            self.manifest.get("feature_schema_sha256") != schema_hash
            or self.info.get("feature_schema_sha256") != schema_hash
            or self.info.get("feature_columns") != FEATURE_COLUMNS
        ):
            self.error = "生产特征版本不匹配"
            return
        if self.manifest.get("dataset_sha256") != self.info.get("dataset_sha256"):
            self.error = "模型数据血缘不匹配"
            return
        if (
            self.info.get("dataset_mode") != "strict"
            or not self.info.get("strict_dataset_ready", False)
            or not self.info.get("point_in_time_universe_verified", False)
            or not self.info.get("point_in_time_security_name_verified", False)
        ):
            self.error = "生产模型不是由就绪的strict数据集训练"
            return
        if self.info.get("research_only", True):
            self.error = "模型仍标记为research_only"
            return
        if not self._policy_valid(self.policy):
            self.error = "生产选择策略不存在或无效"
            return
        try:
            if self.kind == "ridge":
                self.payload = self._load_json(model_path)
                if not self.payload:
                    self.error = "岭回归模型文件不存在"
                elif self.payload.get("feature_columns") != FEATURE_COLUMNS:
                    self.error = "岭回归特征版本不匹配"
                elif not self._ridge_payload_valid(self.payload):
                    self.error = "岭回归模型参数形状或数值无效"
            elif self.kind == "lightgbm":
                with model_path.open("rb") as handle:
                    self.model = pickle.load(handle)
                if list(getattr(self.model, "feature_columns", [])) != FEATURE_COLUMNS:
                    self.error = "LightGBM特征版本不匹配"
            else:
                self.error = "没有已发布的模型类型"
        except (OSError, ValueError, TypeError, KeyError, pickle.PickleError) as exc:
            self.error = f"模型加载失败: {exc}"

    def _artifact_path(self, filename: Any) -> Optional[Path]:
        """Resolve only flat artifact names inside the configured model dir."""

        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            return None
        candidate = (self.model_dir / filename).resolve()
        try:
            if candidate.parent != self.model_dir.resolve():
                return None
        except OSError:
            return None
        return candidate

    @staticmethod
    def _ridge_payload_valid(payload: Dict[str, Any]) -> bool:
        width = len(FEATURE_COLUMNS)
        expected = {
            "medians": width,
            "means": width,
            "scales": width,
            "return_coef": width + 1,
            "positive_coef": width + 1,
            "hit_coef": width + 1,
            "loss_coef": width + 1,
        }
        try:
            arrays = {
                key: np.asarray(payload[key], dtype=float).reshape(-1)
                for key in expected
            }
        except (KeyError, TypeError, ValueError):
            return False
        if any(len(arrays[key]) != length for key, length in expected.items()):
            return False
        if any(not np.isfinite(value).all() for value in arrays.values()):
            return False
        return bool((arrays["scales"] > 0).all())

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _matches_hash(path: Path, expected) -> bool:
        if not path.is_file() or not isinstance(expected, str) or len(expected) != 64:
            return False
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return False
        return digest.hexdigest() == expected

    @property
    def available(self) -> bool:
        return not self.error and (bool(self.payload) or self.model is not None)

    @staticmethod
    def _policy_valid(policy: Dict[str, Any]) -> bool:
        if not isinstance(policy, dict):
            return False
        try:
            if int(policy.get("max_positions", 0) or 0) != 1:
                return False
        except (TypeError, ValueError):
            return False
        if policy.get("contract_version") != "v4-selection-policy-v1":
            return False
        if policy.get("feature_columns") != FEATURE_COLUMNS:
            return False
        if policy.get("score_column") not in {
            "predicted_return",
            "predicted_positive_probability",
            "selection_score",
        }:
            return False
        for key in (
            "minimum_predicted_return",
            "minimum_positive_probability",
            "maximum_large_loss_probability",
            "minimum_regime_score",
        ):
            value = policy.get(key)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                return False
        return True

    def _validated_frame(self, features: Dict[str, Any]) -> Optional[pd.DataFrame]:
        self.last_prediction_error = ""
        if not isinstance(features, dict):
            self.last_prediction_error = "实时特征不存在"
            return None
        missing = [name for name in FEATURE_COLUMNS if name not in features]
        if missing:
            self.last_prediction_error = f"实时特征缺失{len(missing)}项"
            return None
        frame = pd.DataFrame([{name: features.get(name) for name in FEATURE_COLUMNS}])
        frame = frame.apply(pd.to_numeric, errors="coerce")
        if frame.isna().any(axis=None):
            self.last_prediction_error = "实时特征存在无效值"
            return None
        return frame

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Score a complete feature frame in one deterministic model call."""

        self.last_prediction_error = ""
        columns = [
            "predicted_return",
            "predicted_positive_probability",
            "predicted_hit_probability",
            "predicted_large_loss_probability",
        ]
        if not self.available or frame is None or frame.empty:
            return pd.DataFrame(columns=columns)
        matrix_frame = frame.reindex(columns=FEATURE_COLUMNS).apply(
            pd.to_numeric, errors="coerce"
        )
        valid = np.isfinite(matrix_frame.to_numpy(dtype=float)).all(axis=1)
        if not bool(valid.any()):
            self.last_prediction_error = "实时特征全部无效"
            return pd.DataFrame(columns=columns)
        matrix_frame = matrix_frame.loc[valid]

        if self.kind == "lightgbm":
            try:
                result = self.model.predict(matrix_frame)
            except (AttributeError, TypeError, ValueError) as exc:
                self.last_prediction_error = f"LightGBM预测失败: {exc}"
                return pd.DataFrame(columns=columns)
            if not isinstance(result, pd.DataFrame):
                self.last_prediction_error = "LightGBM预测格式无效"
                return pd.DataFrame(columns=columns)
            result = result.reindex(columns=columns)
            if not np.isfinite(result.to_numpy(dtype=float)).all():
                self.last_prediction_error = "LightGBM预测包含无效数值"
                return pd.DataFrame(columns=columns)
            return result

        values = matrix_frame.to_numpy(dtype=float)
        medians = np.asarray(self.payload["medians"], dtype=float)
        means = np.asarray(self.payload["means"], dtype=float)
        scales = np.asarray(self.payload["scales"], dtype=float)
        values = np.where(np.isfinite(values), values, medians)
        values = np.clip((values - means) / scales, -8.0, 8.0)
        matrix = np.column_stack([np.ones(len(values)), values])

        def linear(name: str, *, probability: bool = False):
            coefficient = np.asarray(self.payload[name], dtype=float)
            predicted = matrix @ coefficient
            return np.clip(predicted, 0.0, 1.0) if probability else predicted

        return pd.DataFrame(
            {
                "predicted_return": linear("return_coef"),
                "predicted_positive_probability": linear(
                    "positive_coef", probability=True
                ),
                "predicted_hit_probability": linear(
                    "hit_coef", probability=True
                ),
                "predicted_large_loss_probability": linear(
                    "loss_coef", probability=True
                ),
            },
            index=matrix_frame.index,
        )

    def predict(self, features: Dict[str, Any]) -> Optional[Dict[str, float]]:
        if not self.available:
            return None
        frame = self._validated_frame(features)
        if frame is None:
            return None

        result = self.predict_frame(frame)
        if result.empty:
            return None
        return {key: float(value) for key, value in result.iloc[0].items()}
