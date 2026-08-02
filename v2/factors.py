"""
V2 因子计算模块 — FactorComputer

计算 21 个量化因子，输入 DataFrame 须包含:
  code, name, open, high, low, close, volume, amount, pct_chg, sector
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class FactorComputer:
    """因子计算器 — 计算全部 21 个因子。"""

    # ── 因子计算参数 ──────────────────────────────────────
    MIN_PERIODS = 20  # 至少需要 20 根 K 线
    CHAN_WINDOW = 15  # 缠论中枢观察窗口
    CHAN_RANGE_PCT = 5.0  # 盘整幅度上限(%)
    CHAN_VOL_RATIO = 1.2  # 突破放量倍数

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算所有因子并添加到 DataFrame。

        Parameters
        ----------
        df : pd.DataFrame
            须含字段: open, high, low, close, volume, amount, pct_chg, sector
            按 code 分组后内部按日期排序。

        Returns
        -------
        pd.DataFrame
            追加因子列后的 DataFrame。
        """
        if df.empty:
            logger.warning("compute() 收到空 DataFrame")
            return df

        # 确保按股票分组内日期有序
        if 'date' in df.columns:
            df = df.sort_values(['code', 'date']).reset_index(drop=True)
        else:
            # 无日期列则假定已排序
            pass

        # 逐股票计算需要滚动历史的因子
        # 将 code 设为 index 再 groupby，确保 code 列保留在结果中
        df = df.set_index('code')
        df = df.groupby(level=0, group_keys=False).apply(
            self._compute_group
        )
        df = df.reset_index()

        # 计算不需要分组滚动历史的截面因子（需已有 log_market_cap 等）
        df = self._compute_cross_factors(df)

        return df

    # ── 组内计算（逐股票滚动历史）───────────────────────────
    def _compute_group(self, grp: pd.DataFrame) -> pd.DataFrame:
        """对单只股票的时间序列计算滚动因子。"""
        df = grp.copy()
        if len(df) < self.MIN_PERIODS:
            logger.debug(f"股票 {df['code'].iloc[0] if 'code' in df else '?'} 数据不足 {self.MIN_PERIODS} 根")
            return df

        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        open_ = df['open'].values.astype(float)
        volume = df['volume'].values.astype(float)
        amount = df['amount'].values.astype(float)
        pct_chg = df['pct_chg'].values.astype(float)
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]  # 第一根用自身

        n = len(df)

        # 1. momentum_1d ── 当日涨跌幅
        df['momentum_1d'] = pct_chg

        # 2-4. momentum_5d / 10d / 20d
        df['momentum_5d'] = self._roc(close, 5) * 100
        df['momentum_10d'] = self._roc(close, 10) * 100
        df['momentum_20d'] = self._roc(close, 20) * 100

        # 5. breakthrough_1d ── 振幅 (high-low)/prev_close*100
        amplitude = np.where(prev_close > 0, (high - low) / prev_close * 100, np.nan)
        df['breakthrough_1d'] = amplitude

        # 6. volume_ratio ── 量比 vol / avg_vol_5d
        avg_vol_5d = self._sma(volume, 5)
        df['volume_ratio'] = np.where(avg_vol_5d > 0, volume / avg_vol_5d, np.nan)

        # 7. volatility_20d ── 20日波动率 std(pct_chg)
        df['volatility_20d'] = self._rolling_std(pct_chg, 20)

        # 8. turn_rate ── 成交额比率 amount / avg_amount_5d
        avg_amount_5d = self._sma(amount, 5)
        df['turn_rate'] = np.where(avg_amount_5d > 0, amount / avg_amount_5d, np.nan)

        # 9. rsi_14d ── 14 日 RSI
        df['rsi_14d'] = self._rsi(pct_chg, 14)

        # 10. amount_stability ── 1 - CV(amount, 5d)
        std_amount_5d = self._rolling_std(amount, 5)
        mean_amount_5d = self._sma(amount, 5)
        cv = np.where(mean_amount_5d > 0, std_amount_5d / mean_amount_5d, np.nan)
        df['amount_stability'] = 1.0 - cv

        # 11. up_down_vol_ratio ── std(上涨量)/std(下跌量)
        df['up_down_vol_ratio'] = self._up_down_vol_ratio(volume, pct_chg, 20)

        # 12. vol_price_sync ── (volume_ratio-1)*pct_chg
        vol_ratio = df['volume_ratio'].values
        df['vol_price_sync'] = np.where(
            np.isfinite(vol_ratio) & np.isfinite(pct_chg),
            (vol_ratio - 1.0) * pct_chg,
            np.nan
        )

        # 16. momentum_accel ── mom_1d - mom_5d
        df['momentum_accel'] = pct_chg - df['momentum_5d'].values

        # 17. overnight_gap ── (今开-昨收)/昨收*100
        gap = np.where(
            prev_close > 0,
            (open_ - prev_close) / prev_close * 100,
            np.nan
        )
        df['overnight_gap'] = gap

        # 18. chan_breakout ── 缠论中枢突破
        df['chan_breakout'] = self._chan_breakout(
            high, low, close, volume,
            window=self.CHAN_WINDOW,
            range_pct=self.CHAN_RANGE_PCT,
            vol_ratio=self.CHAN_VOL_RATIO
        )

        # 19. price_vs_poc ── (现价-POC)/POC*100
        df['price_vs_poc'] = self._price_vs_poc(close, volume, 20)

        # 21. dist_to_20d_high ── 距20日高点距离
        df['dist_to_20d_high'] = self._dist_to_high(close, high, 20)

        return df

    # ── 截面因子（需全市场数据）───────────────────────────
    def _compute_cross_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算需要截面信息的因子。"""
        # 13-15 在 data.py 中通过 EastMoney 获取后赋值
        # 20 需要行业数据，在 data.py 中计算
        return df

    # ============================================================
    #  内部工具方法
    # ============================================================

    @staticmethod
    def _roc(arr: np.ndarray, period: int) -> np.ndarray:
        """Rate of Change: arr[t] / arr[t-period] - 1"""
        result = np.full_like(arr, np.nan, dtype=float)
        if period >= len(arr):
            return result
        result[period:] = arr[period:] / arr[:-period] - 1.0
        return result

    @staticmethod
    def _sma(arr: np.ndarray, period: int) -> np.ndarray:
        """Simple moving average (向前)."""
        result = np.full_like(arr, np.nan, dtype=float)
        if period > len(arr):
            return result
        cum = np.cumsum(arr, dtype=float)
        result[period - 1:] = cum[period - 1:] / period
        result[period - 1:] -= np.concatenate([[0], cum[:len(arr) - period]]) / period
        return result

    @staticmethod
    def _rolling_std(arr: np.ndarray, period: int) -> np.ndarray:
        """Rolling standard deviation."""
        result = np.full_like(arr, np.nan, dtype=float)
        if period > len(arr):
            return result
        for i in range(period - 1, len(arr)):
            result[i] = np.std(arr[i - period + 1:i + 1], ddof=0)
        return result

    @staticmethod
    def _rsi(pct_chg: np.ndarray, period: int = 14) -> np.ndarray:
        """RSI 计算。"""
        result = np.full_like(pct_chg, np.nan, dtype=float)
        if period >= len(pct_chg):
            return result
        gains = np.where(pct_chg > 0, pct_chg, 0.0)
        losses = np.where(pct_chg < 0, -pct_chg, 0.0)
        avg_gain = np.mean(gains[1:period + 1])
        avg_loss = np.mean(losses[1:period + 1])
        for i in range(period, len(pct_chg)):
            if i > period:
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                result[i] = 100.0 if avg_gain > 0 else 50.0
            else:
                rs = avg_gain / avg_loss
                result[i] = 100.0 - 100.0 / (1.0 + rs)
        return result

    @staticmethod
    def _up_down_vol_ratio(volume: np.ndarray, pct_chg: np.ndarray,
                           period: int) -> np.ndarray:
        """std(上涨量) / std(下跌量)。"""
        result = np.full_like(volume, np.nan, dtype=float)
        if period > len(volume):
            return result
        for i in range(period - 1, len(volume)):
            chunk_v = volume[i - period + 1:i + 1]
            chunk_p = pct_chg[i - period + 1:i + 1]
            up_vol = chunk_v[chunk_p > 0]
            down_vol = chunk_v[chunk_p < 0]
            std_up = np.std(up_vol) if len(up_vol) > 1 else 1.0
            std_down = np.std(down_vol) if len(down_vol) > 1 else 1.0
            if std_down == 0:
                result[i] = np.nan
            else:
                result[i] = std_up / std_down
        return result

    @staticmethod
    def _chan_breakout(high: np.ndarray, low: np.ndarray,
                       close: np.ndarray, volume: np.ndarray,
                       window: int = 15, range_pct: float = 5.0,
                       vol_ratio: float = 1.2) -> np.ndarray:
        """
        缠论中枢突破信号。

        规则:
          1. 前 window 日最高-最低 < range_pct% * 最新收盘价 (窄幅盘整)
          2. 今日收盘突破前 window 日最高价
          3. 今日量比 > vol_ratio

        返回 0/1 数组。
        """
        result = np.zeros(len(close), dtype=float)
        if window >= len(close):
            return result

        for i in range(window, len(close)):
            seg_high = np.max(high[i - window:i])
            seg_low = np.min(low[i - window:i])
            ref_close = close[i - 1] if i > 0 else close[i]
            # 盘整幅度
            if ref_close > 0 and (seg_high - seg_low) / ref_close * 100 > range_pct:
                continue
            # 突破上沿
            if close[i] <= seg_high:
                continue
            # 放量
            avg_vol = np.mean(volume[i - window:i])
            if avg_vol > 0 and volume[i] / avg_vol < vol_ratio:
                continue
            result[i] = 1.0
        return result

    @staticmethod
    def _price_vs_poc(close: np.ndarray, volume: np.ndarray,
                      period: int = 20) -> np.ndarray:
        """
        (现价 - 20日成交量 POC) / POC * 100

        POC (Point of Control) = 成交量加权均价。
        """
        result = np.full_like(close, np.nan, dtype=float)
        if period > len(close):
            return result
        for i in range(period - 1, len(close)):
            seg_v = volume[i - period + 1:i + 1]
            seg_c = close[i - period + 1:i + 1]
            total_v = np.sum(seg_v)
            if total_v > 0:
                poc = np.sum(seg_c * seg_v) / total_v
                result[i] = (close[i] - poc) / poc * 100
        return result

    @staticmethod
    def _dist_to_high(close: np.ndarray, high: np.ndarray,
                      period: int = 20) -> np.ndarray:
        """(close - 20d高点) / 20d高点 * 100"""
        result = np.full_like(close, np.nan, dtype=float)
        if period > len(close):
            return result
        for i in range(period - 1, len(close)):
            hi = np.max(high[i - period + 1:i + 1])
            if hi > 0:
                result[i] = (close[i] - hi) / hi * 100
        return result
