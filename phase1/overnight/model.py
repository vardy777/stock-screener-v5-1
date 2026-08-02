"""Time-aware multi-target models for the overnight strategy.

The production decision is deliberately separated into four questions:
expected net return, probability of any net profit, probability of clearing
the 1% target, and probability of a large loss.  Keeping those targets
separate prevents a high average-return forecast from hiding poor precision or
unacceptable downside risk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd


class RidgeSignalModel:
    """Small dependency-free baseline model with deterministic behaviour."""

    name = "ridge"

    def __init__(self, feature_columns: Sequence[str], alpha: float = 5.0):
        self.feature_columns = list(feature_columns)
        self.alpha = float(alpha)
        self.medians = None
        self.means = None
        self.scales = None
        self.return_coef = None
        self.positive_coef = None
        self.hit_coef = None
        self.loss_coef = None

    def _raw_matrix(self, frame: pd.DataFrame) -> np.ndarray:
        data = frame.reindex(columns=self.feature_columns).apply(
            pd.to_numeric, errors="coerce"
        )
        return data.replace([np.inf, -np.inf], np.nan).to_numpy(dtype=float)

    def _transform(self, frame: pd.DataFrame, *, fit: bool) -> np.ndarray:
        matrix = self._raw_matrix(frame)
        if fit:
            self.medians = np.nanmedian(matrix, axis=0)
            self.medians = np.where(np.isfinite(self.medians), self.medians, 0.0)
        matrix = np.where(np.isfinite(matrix), matrix, self.medians)
        if fit:
            self.means = matrix.mean(axis=0)
            self.scales = matrix.std(axis=0)
            self.scales = np.where(self.scales > 1e-12, self.scales, 1.0)
        matrix = (matrix - self.means) / self.scales
        matrix = np.clip(matrix, -8.0, 8.0)
        return np.column_stack([np.ones(len(matrix)), matrix])

    def _solve(self, matrix: np.ndarray, target: np.ndarray) -> np.ndarray:
        penalty = np.eye(matrix.shape[1], dtype=float) * self.alpha
        penalty[0, 0] = 0.0
        lhs = matrix.T @ matrix + penalty
        rhs = matrix.T @ target
        return np.linalg.pinv(lhs) @ rhs

    def fit(self, frame: pd.DataFrame) -> "RidgeSignalModel":
        matrix = self._transform(frame, fit=True)
        returns = pd.to_numeric(frame["net_return"], errors="coerce").fillna(0.0)
        returns = np.clip(returns.to_numpy(dtype=float), -0.20, 0.20)
        hits = pd.to_numeric(frame["target_1pct"], errors="coerce").fillna(0.0)
        hits = hits.to_numpy(dtype=float)
        positive = (returns > 0.0).astype(float)
        losses = pd.to_numeric(frame["large_loss"], errors="coerce").fillna(0.0)
        losses = losses.to_numpy(dtype=float)
        self.return_coef = self._solve(matrix, returns)
        self.positive_coef = self._solve(matrix, positive)
        self.hit_coef = self._solve(matrix, hits)
        self.loss_coef = self._solve(matrix, losses)
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        if any(
            coef is None
            for coef in (
                self.return_coef,
                self.positive_coef,
                self.hit_coef,
                self.loss_coef,
            )
        ):
            raise RuntimeError("model must be fitted before prediction")
        matrix = self._transform(frame, fit=False)
        return pd.DataFrame(
            {
                "predicted_return": matrix @ self.return_coef,
                "predicted_positive_probability": np.clip(
                    matrix @ self.positive_coef, 0.0, 1.0
                ),
                "predicted_hit_probability": np.clip(matrix @ self.hit_coef, 0.0, 1.0),
                "predicted_large_loss_probability": np.clip(
                    matrix @ self.loss_coef, 0.0, 1.0
                ),
            },
            index=frame.index,
        )

    def feature_importance(self) -> pd.DataFrame:
        if self.return_coef is None:
            return pd.DataFrame(columns=["feature", "importance"])
        values = np.abs(self.return_coef[1:])
        total = values.sum()
        if total > 0:
            values = values / total
        return pd.DataFrame(
            {"feature": self.feature_columns, "importance": values}
        ).sort_values("importance", ascending=False)

    def save(self, path: Path) -> None:
        payload = {
            "model": self.name,
            "feature_columns": self.feature_columns,
            "alpha": self.alpha,
            "medians": self.medians.tolist(),
            "means": self.means.tolist(),
            "scales": self.scales.tolist(),
            "return_coef": self.return_coef.tolist(),
            "positive_coef": self.positive_coef.tolist(),
            "hit_coef": self.hit_coef.tolist(),
            "loss_coef": self.loss_coef.tolist(),
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)


class LightGBMSignalModel:
    name = "lightgbm"

    def __init__(self, feature_columns: Sequence[str], random_state: int = 42):
        import lightgbm as lgb

        self.feature_columns = list(feature_columns)
        common = {
            "n_estimators": 250,
            "learning_rate": 0.035,
            "num_leaves": 31,
            "max_depth": 6,
            "min_child_samples": 100,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_lambda": 2.0,
            "random_state": random_state,
            "verbosity": -1,
            "n_jobs": -1,
        }
        self.return_model = lgb.LGBMRegressor(objective="huber", **common)
        self.positive_model = lgb.LGBMClassifier(objective="binary", **common)
        self.hit_model = lgb.LGBMClassifier(objective="binary", **common)
        self.loss_model = lgb.LGBMClassifier(objective="binary", **common)

    def _matrix(self, frame: pd.DataFrame) -> pd.DataFrame:
        return (
            frame.reindex(columns=self.feature_columns)
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )

    def fit(self, frame: pd.DataFrame) -> "LightGBMSignalModel":
        matrix = self._matrix(frame)
        returns = np.clip(
            pd.to_numeric(frame["net_return"], errors="coerce").fillna(0.0),
            -0.20,
            0.20,
        )
        hits = pd.to_numeric(frame["target_1pct"], errors="coerce").fillna(0).astype(int)
        positive = (
            pd.to_numeric(frame["net_return"], errors="coerce").fillna(0.0) > 0.0
        ).astype(int)
        losses = pd.to_numeric(frame["large_loss"], errors="coerce").fillna(0).astype(int)
        self.return_model.fit(matrix, returns)
        self.positive_model.fit(matrix, positive)
        self.hit_model.fit(matrix, hits)
        self.loss_model.fit(matrix, losses)
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        matrix = self._matrix(frame)
        return pd.DataFrame(
            {
                "predicted_return": self.return_model.predict(matrix),
                "predicted_positive_probability": self.positive_model.predict_proba(matrix)[:, 1],
                "predicted_hit_probability": self.hit_model.predict_proba(matrix)[:, 1],
                "predicted_large_loss_probability": self.loss_model.predict_proba(matrix)[:, 1],
            },
            index=frame.index,
        )

    def feature_importance(self) -> pd.DataFrame:
        values = np.asarray(self.return_model.feature_importances_, dtype=float)
        total = values.sum()
        if total > 0:
            values /= total
        return pd.DataFrame(
            {"feature": self.feature_columns, "importance": values}
        ).sort_values("importance", ascending=False)

    def save(self, path: Path) -> None:
        import pickle

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            pickle.dump(self, handle)


def create_model(feature_columns: Sequence[str], kind: str = "auto"):
    kind = kind.lower()
    if kind not in {"auto", "ridge", "lightgbm"}:
        raise ValueError(f"unknown model kind: {kind}")
    if kind in {"auto", "lightgbm"}:
        try:
            return LightGBMSignalModel(feature_columns)
        except ImportError:
            if kind == "lightgbm":
                raise
    return RidgeSignalModel(feature_columns)
