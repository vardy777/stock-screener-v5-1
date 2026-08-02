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

            values = df[raw] if raw and raw in df.columns else (
                df[col] if col in df.columns else None
            )

            if values is None:
                df[f'{col}_norm'] = 50.0
                continue

            # 使用平均秩处理并列值；常量因子必须保持中性，不能按输入/代码
            # 顺序凭空制造0~100分差异。
            numeric = pd.to_numeric(values, errors='coerce').replace(
                [np.inf, -np.inf], np.nan
            )
            valid = numeric.dropna()
            normed = pd.Series(50.0, index=df.index, dtype=float)
            if len(valid) > 1 and valid.nunique(dropna=True) > 1:
                ranks = valid.rank(method='average')
                normed.loc[valid.index] = (ranks - 1.0) / (len(valid) - 1.0) * 100.0

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
