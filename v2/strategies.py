"""
V2 策略层 — 三大选股策略 + 市场自适应配額

BreakthroughStrategy : 缠论中枢突破 + 放量确认 + 距20日高点 ≤ 3%
MomentumStrategy    : RSI 温和强势 + 成交稳定 + 不低开
OversoldStrategy    : 真超跌 + RSI 超卖 + 缩量

MarketAdaptiveAllocator : 根据上证指数涨跌分配各策略配额
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DAILY_MAX
# ---------------------------------------------------------------------------
DAILY_MAX: int = 5

# ---------------------------------------------------------------------------
# BaseStrategy
# ---------------------------------------------------------------------------

class BaseStrategy(ABC):
    """策略基类。

    Parameters
    ----------
    name : str
        策略名（如 "breakthrough"、"momentum"、"oversold"）
    """

    def __init__(self, name: str):
        self.name = name
        self._candidates_cache: Optional[pd.DataFrame] = None

    @abstractmethod
    def filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """对传入的因子 DataFrame 应用策略过滤器，返回符合条件的子集。"""
        ...

    def score_and_sort(self, df: pd.DataFrame) -> pd.DataFrame:
        """确保 final_score 列存在并按降序排列。"""
        if df is None or df.empty:
            return pd.DataFrame()
        if "final_score" not in df.columns:
            df["final_score"] = 0.0
        return df.sort_values("final_score", ascending=False).reset_index(drop=True)

    def get_candidates(self, df: pd.DataFrame) -> pd.DataFrame:
        """对外接口：filter -> score_and_sort。"""
        filtered = self.filter(df)
        if filtered is None or filtered.empty:
            self._candidates_cache = pd.DataFrame()
        else:
            self._candidates_cache = self.score_and_sort(filtered)
        return self._candidates_cache

    @property
    def candidates(self) -> pd.DataFrame:
        """最近一次 get_candidates 的结果。"""
        return self._candidates_cache if self._candidates_cache is not None else pd.DataFrame()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"


# ---------------------------------------------------------------------------
# BreakthroughStrategy
# ---------------------------------------------------------------------------

class BreakthroughStrategy(BaseStrategy):
    """缠论中枢突破策略。

    Filters:
        chan_breakout >= 0.5         (中枢突破信号)
        volume_ratio >= 1.3          (放量确认)
        dist_to_20d_high >= -3.0     (距20日高点 ≤ 3%)
        sector_strength >= -1.0      (板块不弱)
        amount >= 3e8                (成交额 ≥ 3 亿)
        price <= 150                 (股价 ≤ 150)
    """

    def __init__(self, name: str = "breakthrough"):
        super().__init__(name)

    def filter(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        mask = pd.Series(True, index=df.index)

        # chan_breakout
        if "chan_breakout" in df.columns:
            mask &= df["chan_breakout"].fillna(0).astype(float) >= 0.5
        else:
            logger.warning("BreakthroughStrategy: 'chan_breakout' column missing, skipping filter")

        # volume_ratio
        if "volume_ratio" in df.columns:
            mask &= df["volume_ratio"].fillna(0).astype(float) >= 1.3
        else:
            logger.warning("BreakthroughStrategy: 'volume_ratio' column missing")

        # dist_to_20d_high
        if "dist_to_20d_high" in df.columns:
            mask &= df["dist_to_20d_high"].fillna(-999).astype(float) >= -3.0

        # sector_strength
        if "sector_strength" in df.columns:
            mask &= df["sector_strength"].fillna(-999).astype(float) >= -1.0

        # amount
        if "amount" in df.columns:
            mask &= df["amount"].fillna(0).astype(float) >= 3e8
        else:
            logger.warning("BreakthroughStrategy: 'amount' column missing")

        # price / close
        price_col = "close" if "close" in df.columns else ("price" if "price" in df.columns else None)
        if price_col:
            mask &= df[price_col].fillna(999).astype(float) <= 150
        else:
            logger.warning("BreakthroughStrategy: no price/close column found")

        result = df.loc[mask].copy()
        logger.info(
            "BreakthroughStrategy: %d / %d stocks passed filters",
            len(result), len(df),
        )
        return result


# ---------------------------------------------------------------------------
# MomentumStrategy
# ---------------------------------------------------------------------------

class MomentumStrategy(BaseStrategy):
    """动量策略。

    Filters:
        45 <= rsi_14d <= 72         (RSI 温和强势)
        amount_stability >= 0.4      (成交稳定)
        overnight_gap >= -0.5        (不低开)
        amount >= 2e8                (成交额 ≥ 2 亿)
        price <= 150                 (股价 ≤ 150)
    """

    def __init__(self, name: str = "momentum"):
        super().__init__(name)

    def filter(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        mask = pd.Series(True, index=df.index)

        # rsi_14d
        if "rsi_14d" in df.columns:
            rsi = df["rsi_14d"].fillna(50).astype(float)
            mask &= (rsi >= 45) & (rsi <= 72)
        else:
            logger.warning("MomentumStrategy: 'rsi_14d' column missing")

        # amount_stability
        if "amount_stability" in df.columns:
            mask &= df["amount_stability"].fillna(0).astype(float) >= 0.4
        else:
            logger.warning("MomentumStrategy: 'amount_stability' column missing")

        # overnight_gap
        if "overnight_gap" in df.columns:
            mask &= df["overnight_gap"].fillna(-999).astype(float) >= -0.5
        else:
            logger.warning("MomentumStrategy: 'overnight_gap' column missing")

        # amount
        if "amount" in df.columns:
            mask &= df["amount"].fillna(0).astype(float) >= 2e8
        else:
            logger.warning("MomentumStrategy: 'amount' column missing")

        # price / close
        price_col = "close" if "close" in df.columns else ("price" if "price" in df.columns else None)
        if price_col:
            mask &= df[price_col].fillna(999).astype(float) <= 150
        else:
            logger.warning("MomentumStrategy: no price/close column found")

        result = df.loc[mask].copy()
        logger.info(
            "MomentumStrategy: %d / %d stocks passed filters",
            len(result), len(df),
        )
        return result


# ---------------------------------------------------------------------------
# OversoldStrategy
# ---------------------------------------------------------------------------

class OversoldStrategy(BaseStrategy):
    """超跌策略。

    Filters:
        pct_chg <= -5.0              (当日跌幅 ≥ 5%)
        rsi_14d <= 38                (RSI 超卖)
        volume_ratio <= 0.8          (缩量，排除放量杀跌)
        amount >= 1e8                (成交额 ≥ 1 亿)
        price <= 150                 (股价 ≤ 150)
    """

    def __init__(self, name: str = "oversold"):
        super().__init__(name)

    def filter(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        mask = pd.Series(True, index=df.index)

        # pct_chg
        pct_col = "pct_chg" if "pct_chg" in df.columns else ("change_pct" if "change_pct" in df.columns else None)
        if pct_col:
            mask &= df[pct_col].fillna(0).astype(float) <= -5.0
        else:
            logger.warning("OversoldStrategy: no pct_chg/change_pct column found")

        # rsi_14d
        if "rsi_14d" in df.columns:
            mask &= df["rsi_14d"].fillna(50).astype(float) <= 38
        else:
            logger.warning("OversoldStrategy: 'rsi_14d' column missing")

        # volume_ratio
        if "volume_ratio" in df.columns:
            mask &= df["volume_ratio"].fillna(999).astype(float) <= 0.8
        else:
            logger.warning("OversoldStrategy: 'volume_ratio' column missing")

        # amount
        if "amount" in df.columns:
            mask &= df["amount"].fillna(0).astype(float) >= 1e8
        else:
            logger.warning("OversoldStrategy: 'amount' column missing")

        # price / close
        price_col = "close" if "close" in df.columns else ("price" if "price" in df.columns else None)
        if price_col:
            mask &= df[price_col].fillna(999).astype(float) <= 150
        else:
            logger.warning("OversoldStrategy: no price/close column found")

        result = df.loc[mask].copy()
        logger.info(
            "OversoldStrategy: %d / %d stocks passed filters",
            len(result), len(df),
        )
        return result


# ---------------------------------------------------------------------------
# MarketAdaptiveAllocator
# ---------------------------------------------------------------------------

class MarketAdaptiveAllocator:
    """市场自适应配额分配器 (多周期判断版)。

    根据多周期市场状态（1日/5日/20日涨跌 + 市场宽度 + 量能变化）
    决定各策略的配额，再综合选出每日最多 DAILY_MAX 支股票。

    Quota table:
        risk_on:    (breakthrough=4, momentum=1, oversold=0)
        risk_off:   (breakthrough=0, momentum=1, oversold=4)
        neutral:    (breakthrough=2, momentum=2, oversold=1)
    """

    # 策略名称顺序
    STRATEGY_KEYS = ("breakthrough", "momentum", "oversold")

    QUOTA_TABLE: Dict[str, Tuple[int, int, int]] = {
        "risk_on": (4, 1, 0),
        "risk_off": (0, 1, 4),
        "neutral": (2, 2, 1),
    }

    def __init__(self, daily_max: int = DAILY_MAX, verbose: bool = False):
        self.daily_max = daily_max
        self.verbose = verbose
        self._mode: str = "neutral"
        self._quotas: Dict[str, int] = {}

    def get_market_mode(self, signal) -> str:
        """根据多周期市场信号判断市场状态。

        Parameters
        ----------
        signal : float or dict
            float: 兼容旧接口，只使用单日涨跌幅
            dict: 来自 DataFetcher.get_market_state() 的完整信号，
                  包含 sh_1d_pct, sh_5d_pct, sh_20d_pct,
                  advance_ratio, volume_ratio, composite

        Returns
        -------
        str
            "risk_on" / "risk_off" / "neutral"
        """
        if isinstance(signal, dict):
            # 多周期: 使用预计算的 composite 评分
            composite = signal.get("composite", 0)
            mode = signal.get("mode_label", "neutral")
            logger.info(
                "Market mode (multi-cycle): %s (composite=%.1f, "
                "1d=%.1f%%, 5d=%.1f%%, 20d=%.1f%%, breadth=%.0f%%)",
                mode, composite,
                signal.get("sh_1d_pct", 0),
                signal.get("sh_5d_pct", 0),
                signal.get("sh_20d_pct", 0),
                signal.get("advance_ratio", 0) * 100,
            )
            self._mode = mode
            return mode
        else:
            # 单日涨跌 (兼容旧接口)
            sh_index_pct = float(signal)
            if sh_index_pct > 0.5:
                self._mode = "risk_on"
            elif sh_index_pct < -0.5:
                self._mode = "risk_off"
            else:
                self._mode = "neutral"
            logger.info("Market mode (legacy): %s (sh_index=%.2f%%)",
                        self._mode, sh_index_pct)
            return self._mode

    def get_quotas(self, mode: Optional[str] = None) -> Dict[str, int]:
        """获取各策略的配额。

        Parameters
        ----------
        mode : str, optional
            "risk_on" / "risk_off" / "neutral"。若不传则用 self._mode。

        Returns
        -------
        Dict[str, int]
            {"breakthrough": N, "momentum": N, "oversold": N}
        """
        mode = mode or self._mode
        quotas = self.QUOTA_TABLE.get(mode, self.QUOTA_TABLE["neutral"])
        self._quotas = dict(zip(self.STRATEGY_KEYS, quotas))
        logger.info("Quotas for %s: %s", mode, self._quotas)
        return self._quotas

    def allocate(
        self,
        df_with_factors: pd.DataFrame,
        strategies: Dict[str, BaseStrategy],
        industry_col: str = "industry",
    ) -> List[Dict[str, Any]]:
        """跨策略综合选股。

        Parameters
        ----------
        df_with_factors : pd.DataFrame
            全市场因子数据，必须包含 'final_score' 列及各策略所需的因子列。
        strategies : Dict[str, BaseStrategy]
            策略字典，key 必须包含 breakthrough / momentum / oversold。
        industry_col : str
            行业列名，用于行业分散。

        Returns
        -------
        List[Dict[str, Any]]
            选中股票列表, 每支含 code/name/strategy/score/price/industry 等信息。
        """
        if df_with_factors is None or df_with_factors.empty:
            logger.warning("Empty DataFrame passed to allocate()")
            return []

        # 1. 各策略筛选候选
        strategy_candidates: Dict[str, pd.DataFrame] = {}
        for key in self.STRATEGY_KEYS:
            strat = strategies.get(key)
            if strat is None:
                logger.warning("Strategy '%s' not found in strategies dict", key)
                continue
            candidates = strat.get_candidates(df_with_factors)
            if candidates is not None and not candidates.empty:
                candidates = candidates.copy()
                candidates["_strategy"] = key
                strategy_candidates[key] = candidates
                if self.verbose:
                    logger.info("  %s: %d candidates", key, len(candidates))

        # 2. 合并并保留同股票的最高分策略
        all_candidates = pd.concat(
            list(strategy_candidates.values()), ignore_index=True, sort=False,
        )
        if all_candidates.empty:
            logger.info("No candidates from any strategy")
            return []

        # 确定代码列
        code_col = self._resolve_code_column(all_candidates)

        # 同股票只保留最高分策略（横向比较）
        all_candidates = self._deduplicate_by_stock(all_candidates, code_col)

        # 3. 按配额分配
        quotas = self.get_quotas()
        selected: List[Dict[str, Any]] = []
        # 先按策略分组，每个策略内按 final_score 降序
        for key in self.STRATEGY_KEYS:
            pool = all_candidates[all_candidates["_strategy"] == key]
            if pool.empty:
                continue
            pool = pool.sort_values("final_score", ascending=False)
            # 行业分散（配额内）
            used_industries: Dict[str, int] = {}
            allocated = 0
            quota = quotas.get(key, 0)

            for _, row in pool.iterrows():
                if allocated >= quota:
                    break

                industry = str(row.get(industry_col, "未知"))
                if used_industries.get(industry, 0) >= 2:
                    continue

                selected.append(self._row_to_dict(row, code_col, industry_col))
                used_industries[industry] = used_industries.get(industry, 0) + 1
                allocated += 1

        # 4. 若不足 DAILY_MAX，放宽行业限制补满
        if len(selected) < self.daily_max:
            selected = self._fill_remaining(
                selected, all_candidates, quotas, code_col, industry_col,
            )

        # 5. 裁剪到 DAILY_MAX
        selected = selected[: self.daily_max]

        logger.info(
            "MarketAdaptiveAllocator: selected %d stocks (mode=%s, quotas=%s)",
            len(selected), self._mode, self._quotas,
        )
        return selected

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_code_column(df: pd.DataFrame) -> str:
        """确定代码列的列名。"""
        for col in ("code", "stock_code", "ts_code", "symbol"):
            if col in df.columns:
                return col
        return df.columns[0]  # fallback

    @staticmethod
    def _deduplicate_by_stock(df: pd.DataFrame, code_col: str) -> pd.DataFrame:
        """同股票出现多次时，只保留 final_score 最高的那行。"""
        if df.empty or code_col not in df.columns:
            return df
        # 按代码分组，选 final_score 最高的行
        idx = df.groupby(code_col)["final_score"].idxmax()
        return df.loc[idx].reset_index(drop=True)

    @staticmethod
    def _row_to_dict(
        row: pd.Series, code_col: str, industry_col: str,
    ) -> Dict[str, Any]:
        """将 DataFrame 行转为输出字典。"""
        d: Dict[str, Any] = {
            "code": str(row.get(code_col, "")),
            "name": str(row.get("name", row.get("stock_name", ""))),
            "strategy": str(row.get("_strategy", "")),
            "final_score": float(row.get("final_score", 0)),
        }
        # 价格
        for price_col in ("close", "price"):
            if price_col in row.index:
                d["price"] = float(row[price_col])
                break
        else:
            d["price"] = 0.0
        # 行业
        d["industry"] = str(row.get(industry_col, ""))
        # 额外字段
        for extra in ("pct_chg", "change_pct", "amount", "rsi_14d", "volume_ratio"):
            if extra in row.index:
                d[extra] = float(row[extra])
        return d

    def _fill_remaining(
        self,
        selected: List[Dict[str, Any]],
        all_candidates: pd.DataFrame,
        quotas: Dict[str, int],
        code_col: str,
        industry_col: str,
    ) -> List[Dict[str, Any]]:
        """不足 DAILY_MAX 时，放宽行业限制（最多 3 支/行业）继续补选。"""
        selected_codes = {s["code"] for s in selected}
        # 已选行业计数
        used_industries: Dict[str, int] = {}
        for s in selected:
            ind = s.get("industry", "未知")
            used_industries[ind] = used_industries.get(ind, 0) + 1

        remaining = all_candidates[
            ~all_candidates[code_col].astype(str).isin(selected_codes)
        ].sort_values("final_score", ascending=False)

        for _, row in remaining.iterrows():
            if len(selected) >= self.daily_max:
                break

            code = str(row.get(code_col, ""))
            industry = str(row.get(industry_col, "未知"))

            # 放宽行业限制：最多 3 支
            if used_industries.get(industry, 0) >= 3:
                continue

            # 检查策略是否还有配额（宽松模式）
            strategy = str(row.get("_strategy", ""))
            current_strategy_count = sum(
                1 for s in selected if s["strategy"] == strategy
            )
            if current_strategy_count >= quotas.get(strategy, 999):
                continue

            selected.append(self._row_to_dict(row, code_col, industry_col))
            used_industries[industry] = used_industries.get(industry, 0) + 1
            selected_codes.add(code)

        return selected

    def __repr__(self) -> str:
        return (
            f"MarketAdaptiveAllocator(mode='{self._mode}', "
            f"quotas={self._quotas}, daily_max={self.daily_max})"
        )
