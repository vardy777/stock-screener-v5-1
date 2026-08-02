"""
V2 策略层 — ICWeightedScorer

IC 动态权重打分器
  1. 加载/保存 factor_ic.json (21因子的IC值)
  2. rank-based ICIR 权重计算
  3. 对DataFrame级因子数据加权生成 final_score
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认 IC 值（来自 SKILL.md 策略文档）
# ---------------------------------------------------------------------------
DEFAULT_IC: Dict[str, float] = {
    "momentum_1d": -0.016,
    "momentum_5d": 0.029,
    "momentum_10d": 0.044,
    "momentum_20d": 0.047,
    "breakthrough_1d": 0.059,
    "volume_ratio": -0.005,
    "volatility_20d": 0.037,
    "turn_rate": -0.006,
    "rsi_14d": 0.050,
    "amount_stability": -0.059,
    "up_down_vol_ratio": 0.029,
    "vol_price_sync": 0.016,
    "log_market_cap": 0.016,
    "pe_ttm": 0.0,
    "pb_mrq": 0.0,
    "momentum_accel": -0.041,
    "overnight_gap": 0.026,
    "chan_breakout": 0.0,
    "price_vs_poc": 0.013,
    "sector_strength": 0.0,
    "dist_to_20d_high": 0.0,
}

# 21因子的标准列表（顺序与SKILL.md一致）
FACTOR_NAMES: List[str] = [
    "momentum_1d", "momentum_5d", "momentum_10d", "momentum_20d",
    "breakthrough_1d", "volume_ratio", "volatility_20d", "turn_rate",
    "rsi_14d", "amount_stability", "up_down_vol_ratio", "vol_price_sync",
    "log_market_cap", "pe_ttm", "pb_mrq", "momentum_accel",
    "overnight_gap", "chan_breakout", "price_vs_poc",
    "sector_strength", "dist_to_20d_high",
]

# 复合/离散因子（没有IC的，权重统一为0）
ZERO_IC_FACTORS = {"chan_breakout", "sector_strength", "dist_to_20d_high", "pe_ttm", "pb_mrq"}

# ---------------------------------------------------------------------------
# ICWeightedScorer
# ---------------------------------------------------------------------------

class ICWeightedScorer:
    """IC 动态权重打分器

    Parameters
    ----------
    ic_path : str or Path, optional
        factor_ic.json 路径。若文件不存在则用 DEFAULT_IC。
    smooth_window : int
        ICIR 衰减窗口（历史期数），默认 1 即只当前 IC。
    epsilon : float
        分母极小值，防止除零。
    """

    def __init__(
        self,
        ic_path: Optional[str] = None,
        smooth_window: int = 1,
        epsilon: float = 1e-8,
    ):
        self.ic_path = ic_path
        self.smooth_window = smooth_window
        self.epsilon = epsilon

        # 原始 IC 字典（从文件或默认值加载）
        self.ic_dict: Dict[str, float] = {}
        # 历史上 IC 序列（用于 ICIR 平滑，每期 append）
        self.ic_history: List[Dict[str, float]] = []
        # 实时计算出的权重 (factor_name -> weight)
        self.weights: Dict[str, float] = {}

        self._load_ic()

    # ------------------------------------------------------------------
    # IC 加载/保存
    # ------------------------------------------------------------------

    def _load_ic(self) -> None:
        """从 factor_ic.json 加载 IC，文件不存在或损坏则 fallback 默认值。"""
        # 尝试从文件加载
        loaded = False
        if self.ic_path and Path(self.ic_path).exists():
            try:
                with open(self.ic_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 支持 {"ic": {...}, "history": [...]} 或直接 {...}
                if isinstance(data, dict) and "ic" in data:
                    self.ic_dict = data["ic"]
                    self.ic_history = data.get("history", [])
                elif isinstance(data, dict):
                    self.ic_dict = data
                else:
                    raise ValueError("Unexpected JSON structure")
                logger.info("Loaded IC from %s (%d factors)", self.ic_path, len(self.ic_dict))
                loaded = True
            except Exception as exc:
                logger.warning("Failed to load IC from %s: %s", self.ic_path, exc)

        if not loaded:
            self.ic_dict = dict(DEFAULT_IC)
            logger.info("Using default IC values (%d factors)", len(self.ic_dict))

        # 确保所有 21 个因子都有 IC 值（缺失的补 0）
        for name in FACTOR_NAMES:
            self.ic_dict.setdefault(name, 0.0)

        # 计算初始权重
        self.compute_weights(self.ic_dict)

    def save_ic(self, path: Optional[str] = None) -> None:
        """将当前 IC 字典和历史写入 JSON 文件。"""
        save_path = path or self.ic_path
        if not save_path:
            logger.warning("No ic_path set, cannot save IC data")
            return

        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        data = {
            "ic": self.ic_dict,
            "history": self.ic_history,
            "weights": self.weights,
        }
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Saved IC data to %s", save_path)

    def update_ic(self, new_ic: Dict[str, float]) -> None:
        """更新 IC 并追加到历史（用于每周 IC 重算）。"""
        self.ic_history.append(dict(self.ic_dict))
        self.ic_dict.update(new_ic)
        self.compute_weights(self.ic_dict)

    # ------------------------------------------------------------------
    # 权重计算 (rank-based ICIR)
    # ------------------------------------------------------------------

    def compute_weights(self, ic_dict: Dict[str, float]) -> Dict[str, float]:
        """基于 IC 绝对值排名的 ICIR 权重。

        步骤:
          1. 只取 IC ≠ 0 且不属于 ZERO_IC_FACTORS 的因子
          2. 对 IC 取绝对值
          3. 在有效因子中排名（1=最小, N=最大）
          4. 权重 = rank / sum(rank)
          5. 其余因子权重 = 0

        Returns
        -------
        Dict[str, float]
            factor_name -> weight (和为 1)
        """
        # 只取有实际 IC 值的因子（排除零 IC 和 ZERO_IC_FACTORS）
        candidates = {}
        for name, ic_val in ic_dict.items():
            if name not in FACTOR_NAMES:
                continue
            if name in ZERO_IC_FACTORS:
                continue  # 完全排除，不参与排名
            if abs(ic_val) < self.epsilon:
                continue  # 近零 IC 不参与排名
            candidates[name] = abs(ic_val)

        # 初始化所有因子权重为 0
        self.weights = {name: 0.0 for name in FACTOR_NAMES}

        if not candidates:
            logger.warning("No valid IC values, using equal weights")
            n = len(candidates) or 1
            equal_w = 1.0 / n
            for name in candidates:
                self.weights[name] = equal_w
            return self.weights

        # 排名
        ic_abs = np.array(list(candidates.values()))
        ranks = self._rankdata(ic_abs)
        total_rank = ranks.sum()
        weights_arr = ranks / total_rank if total_rank > 0 else np.zeros_like(ranks)

        # 写回字典
        for idx, name in enumerate(candidates.keys()):
            self.weights[name] = float(weights_arr[idx])

        logger.debug("Computed weights for %d factors (sum=%.6f)", len(candidates), sum(self.weights.values()))
        return self.weights

    @staticmethod
    def _rankdata(values: np.ndarray) -> np.ndarray:
        """平均排名 (1-based)，与 scipy.stats.rankdata 兼容。"""
        n = len(values)
        if n == 0:
            return np.array([], dtype=float)
        # sorter: 按值排序后的索引
        sorter = np.argsort(values, kind="mergesort")
        # 分配顺序排名 (1,2,3,...)
        ordinal = np.empty(n, dtype=float)
        ordinal[sorter] = np.arange(1, n + 1, dtype=float)

        # 处理并列：相同值的排名取平均
        sorted_vals = values[sorter]
        i = 0
        while i < n:
            j = i
            while j < n and abs(sorted_vals[j] - sorted_vals[i]) < 1e-12:
                j += 1
            if j > i + 1:
                avg_rank = (i + 1 + j) / 2.0  # 平均排名
                for k in range(i, j):
                    # 找到 ordinal 中对应原始索引的位置
                    original_idx = sorter[k]
                    ordinal[original_idx] = avg_rank
            i = j

        return ordinal

    # ------------------------------------------------------------------
    # 打分
    # ------------------------------------------------------------------

    def score(self, df_with_factors: pd.DataFrame) -> pd.DataFrame:
        """对包含因子的 DataFrame 添加 'final_score' 列。

        Parameters
        ----------
        df_with_factors : pd.DataFrame
            必须包含 FACTOR_NAMES 中的列（或子集）。

        Returns
        -------
        pd.DataFrame
            新增 'final_score' 列，按 final_score 降序排列。
        """
        if df_with_factors is None or df_with_factors.empty:
            logger.warning("Empty DataFrame passed to score()")
            if df_with_factors is not None:
                df_with_factors["final_score"] = 0.0
            return df_with_factors

        df = df_with_factors.copy()

        # 逐因子加权求和
        final = np.zeros(len(df), dtype=float)
        factor_used = 0
        for name, w in self.weights.items():
            if w == 0.0:
                continue
            if name in df.columns:
                col = df[name].fillna(0).values.astype(float)
                final += w * col
                factor_used += 1
            else:
                logger.debug("Factor '%s' not in DataFrame columns, skipped", name)

        if factor_used == 0:
            logger.warning("No factor columns matched, final_score will be 0")
            final[:] = 0.0

        df["final_score"] = np.round(final, 4)
        df.sort_values("final_score", ascending=False, inplace=True)
        # 确保 final_score 列在最后（视觉上更好）
        cols = [c for c in df.columns if c != "final_score"] + ["final_score"]
        df = df[cols]
        return df

    def get_weights_summary(self) -> pd.DataFrame:
        """返回权重汇总 DataFrame：因子名、IC、权重。"""
        rows = []
        for name in FACTOR_NAMES:
            rows.append({
                "factor": name,
                "ic": self.ic_dict.get(name, 0.0),
                "weight": self.weights.get(name, 0.0),
            })
        return pd.DataFrame(rows)

    def __repr__(self) -> str:
        return (
            f"ICWeightedScorer(factors={len(self.ic_dict)}, "
            f"nonzero_weights={sum(1 for v in self.weights.values() if v > 0)})"
        )
