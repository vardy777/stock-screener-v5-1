"""Load only research-approved V4 model artifacts and score live feature rows."""

from __future__ import annotations

import json
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

    def __init__(self):
        self.info = self._load_json(MODEL_DIR / "training_info.json")
        self.kind = str(self.info.get("model", ""))
        self.model = None
        self.payload: Dict[str, Any] = {}
        self.error = ""
        self.last_prediction_error = ""
        if self.info.get("research_only", True):
            self.error = "模型仍标记为research_only"
            return
        try:
            if self.kind == "ridge":
                path = MODEL_DIR / "overnight_ridge.json"
                self.payload = self._load_json(path)
                if not self.payload:
                    self.error = "岭回归模型文件不存在"
            elif self.kind == "lightgbm":
                path = MODEL_DIR / "overnight_lightgbm.pkl"
                with path.open("rb") as handle:
                    self.model = pickle.load(handle)
            else:
                self.error = "没有已发布的模型类型"
        except (OSError, ValueError, pickle.PickleError) as exc:
            self.error = f"模型加载失败: {exc}"

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    @property
    def available(self) -> bool:
        return not self.error and (bool(self.payload) or self.model is not None)

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
        if frame.isna().all(axis=None):
            self.last_prediction_error = "实时特征全部无效"
            return None
        return frame

    def predict(self, features: Dict[str, Any]) -> Optional[Dict[str, float]]:
        if not self.available:
            return None
        frame = self._validated_frame(features)
        if frame is None:
            return None

        if self.kind == "lightgbm":
            result = self.model.predict(frame).iloc[0]
            return {key: float(value) for key, value in result.items()}

        values = frame.reindex(columns=FEATURE_COLUMNS).to_numpy(dtype=float)[0]
        medians = np.asarray(self.payload["medians"], dtype=float)
        means = np.asarray(self.payload["means"], dtype=float)
        scales = np.asarray(self.payload["scales"], dtype=float)
        values = np.where(np.isfinite(values), values, medians)
        values = np.clip((values - means) / scales, -8.0, 8.0)
        matrix = np.concatenate(([1.0], values))

        def linear(name: str, *, probability: bool = False) -> float:
            coefficient = np.asarray(self.payload[name], dtype=float)
            value = float(matrix @ coefficient)
            return float(np.clip(value, 0.0, 1.0)) if probability else value

        return {
            "predicted_return": linear("return_coef"),
            "predicted_positive_probability": linear(
                "positive_coef", probability=True
            ),
            "predicted_hit_probability": linear("hit_coef", probability=True),
            "predicted_large_loss_probability": linear(
                "loss_coef", probability=True
            ),
        }
