"""V3 打分器 — 固定权重, 百分位归一化"""
import numpy as np
import pandas as pd
from v3.factors import FACTOR_WEIGHTS


class UltraShortScorer:
    """超短固定权重打分器"""

    FACTOR_NAMES = list(FACTOR_WEIGHTS.keys())

    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        """对包含因子的DataFrame打分, 返回排序后的df"""
        if df is None or df.empty:
            return df

        df = df.copy()

        # 1. 对每个因子做百分位归一化 (0~100)
        for factor in self.FACTOR_NAMES:
            col = factor  # 因子列名
            raw = f'{factor}_raw' if f'{factor}_raw' in df.columns else None

            values = df[raw].values if raw and raw in df.columns else (
                df[col].values if col in df.columns else None
            )

            if values is None:
                df[f'{col}_norm'] = 50.0
                continue

            # 百分位排名 0~100
            n = len(values)
            if n > 1:
                ranks = np.argsort(np.argsort(values))
                normed = ranks / (n - 1) * 100
            else:
                normed = np.array([50.0])

            # 反转权重: 市值因子越小越好
            if factor == 'log_market_cap':
                normed = 100 - normed

            df[f'{col}_norm'] = normed

        # 2. 加权求和
        total = np.zeros(len(df))
        for factor, weight in FACTOR_WEIGHTS.items():
            col = f'{factor}_norm'
            if col in df.columns:
                total += weight * df[col].values

        df['final_score'] = np.round(total, 2)

        # 3. 排序
        df.sort_values('final_score', ascending=False, inplace=True)
        return df
