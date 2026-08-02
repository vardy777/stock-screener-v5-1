"""V3 超短因子 (6个, 针对尾盘买入/次日卖出场景)"""
import numpy as np
import pandas as pd

FACTOR_WEIGHTS = {
    'close_position': 0.35,    # 日内位置 (核心)
    'afternoon_momentum': 0.20,  # 尾盘涨幅
    'relative_strength': 0.15,   # 板块相对强度
    'zt_momentum': 0.10,         # 涨停基因
    'log_market_cap': 0.10,      # 小盘优先
    'volume_ratio': 0.10,        # 量比
}

class UltraShortFactorComputer:
    """超短因子计算器"""

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """对DataFrame计算6个因子, 返回添加因子列后的df"""
        df = df.copy()

        # 1. close_position (日内位置)
        # (close - low) / (high - low), 0~1
        if all(c in df.columns for c in ['close', 'low', 'high']):
            range_ = df['high'] - df['low']
            df['close_position'] = np.where(
                range_ > 0, (df['close'] - df['low']) / range_, 0.5
            )

        # 2. afternoon_momentum (尾盘涨幅)
        # 使用当日涨跌幅 (在free API限制下, 用全天涨幅近似)
        if 'pct_chg' in df.columns:
            df['afternoon_momentum'] = df['pct_chg']

        # 3. relative_strength (板块相对强度)
        # 个股涨幅 - 同行业平均涨幅
        if 'pct_chg' in df.columns and 'sector' in df.columns:
            sector_mean = df.groupby('sector')['pct_chg'].transform('mean')
            df['relative_strength'] = df['pct_chg'] - sector_mean
        elif 'pct_chg' in df.columns:
            df['relative_strength'] = df['pct_chg'] - df['pct_chg'].mean()

        # 4. zt_momentum (涨停基因)
        # 近3日是否有涨停。没有历史数据时, 用今日大幅上涨近似
        if 'pct_chg' in df.columns:
            # 今日涨幅>7%视为有涨停潜力
            df['zt_momentum'] = np.where(df['pct_chg'] >= 7, 1.0,
                                         np.where(df['pct_chg'] >= 5, 0.5, 0.0))
        else:
            df['zt_momentum'] = 0.0

        # 5. log_market_cap (流通市值对数)
        if 'market_cap' in df.columns:
            df['log_market_cap'] = np.log10(df['market_cap'].clip(lower=1))
        else:
            df['log_market_cap'] = np.log10(50e8)  # 默认50亿

        # 6. volume_ratio (量比)
        if 'volume_ratio' in df.columns:
            df['volume_ratio_raw'] = df['volume_ratio']
        else:
            df['volume_ratio_raw'] = 1.0

        return df
