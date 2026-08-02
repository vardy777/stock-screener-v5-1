"""
V2 截面标准化模块 — CrossSectionNormalizer

工作流程:
  1. 按行业(sector)分组，组内 z-score 标准化每个因子
  2. 跨行业排名，映射到 0-100 百分位

输出列在原因子名后加 '_norm' 后缀。
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class CrossSectionNormalizer:
    """
    截面标准化器。

    两步标准化:
      Step 1 — Within-industry z-score (去行业影响)
      Step 2 — Cross-sector rank -> percentile 0-100
    """

    def __init__(self, clip_z: float = 4.0):
        """
        Parameters
        ----------
        clip_z : float
            z-score 截断阈值，防止极端值污染排名。
        """
        self.clip_z = clip_z

    def normalize(self, df: pd.DataFrame,
                  factor_columns: list[str]) -> pd.DataFrame:
        """
        对指定因子列执行两步截面标准化。

        Parameters
        ----------
        df : pd.DataFrame
            须含 'sector' 列及 factor_columns 列。
        factor_columns : list[str]
            需要标准化的因子列名。

        Returns
        -------
        pd.DataFrame
            追加 '_norm' 列后的 DataFrame。
        """
        if df.empty:
            logger.warning("normalize() 收到空 DataFrame")
            return df

        if 'sector' not in df.columns:
            logger.warning("DataFrame 缺少 sector 列，跳过行业标准化，使用全市场排名")
            return self._rank_only(df, factor_columns)

        missing = [c for c in factor_columns if c not in df.columns]
        if missing:
            logger.warning(f"以下因子列不存在: {missing}")
            factor_columns = [c for c in factor_columns if c in df.columns]

        if not factor_columns:
            return df

        result = df.copy()

        for col in factor_columns:
            norm_col = f"{col}_norm"

            # ── Step 1: 行业内 z-score ──
            z_series = result.groupby('sector')[col].transform(
                lambda x: self._zscore(x, clip=self.clip_z)
            )

            # ── Step 2: 跨行业排名 -> 0-100 ──
            # 使用稠密排名，避免平值浪费
            valid = z_series.notna()
            rank = pd.Series(np.nan, index=result.index)
            if valid.any():
                # rank(method='average') 后线性映射到 0-100
                raw_rank = z_series[valid].rank(method='average', pct=False)
                n = raw_rank.max()
                if n > 0:
                    rank[valid] = (raw_rank - 1) / (n - 1) * 100.0
                else:
                    rank[valid] = 50.0  # 单值情况

            result[norm_col] = rank.round(2)

        return result

    # ── 内部方法 ──────────────────────────────────────────

    @staticmethod
    def _zscore(series: pd.Series, clip: float = 4.0) -> pd.Series:
        """组内 z-score，含截断。"""
        if len(series) < 2:
            return pd.Series(np.nan, index=series.index)

        mean = series.mean()
        std = series.std(ddof=0)
        if std == 0 or np.isnan(std):
            return pd.Series(0.0, index=series.index)

        z = (series - mean) / std
        # 截断极端值
        z = z.clip(-clip, clip)
        return z

    def _rank_only(self, df: pd.DataFrame,
                   factor_columns: list[str]) -> pd.DataFrame:
        """无行业信息时，直接全市场排名映射到 0-100。"""
        result = df.copy()
        for col in factor_columns:
            norm_col = f"{col}_norm"
            if col not in result.columns:
                continue
            valid = result[col].notna()
            rank = pd.Series(np.nan, index=result.index)
            if valid.any():
                raw = result[col][valid].rank(method='average', pct=False)
                n = raw.max()
                if n > 0:
                    rank[valid] = (raw - 1) / (n - 1) * 100.0
                else:
                    rank[valid] = 50.0
            result[norm_col] = rank.round(2)
        return result
