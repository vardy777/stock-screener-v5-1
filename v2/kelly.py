"""
V2 策略层 — Kelly 仓位计算 + 结算引擎

KellyPositionSizer : 标准 Kelly 公式 (f* = (p*b - q)/b)
SettlementEngine    : 结算计分、胜率统计、自适应配额 / 权重
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# KellyPositionSizer
# ---------------------------------------------------------------------------

class KellyPositionSizer:
    """Kelly 仓位计算器。

    公式: f* = (p * b - q) / b
    其中:
        p = win_rate (胜率)
        q = 1 - p
        b = avg_win / |avg_loss| (盈亏比)

    f* 上限 50%，下限 0。
    """

    def __init__(self, max_kelly: float = 0.5, min_kelly: float = 0.0):
        self.max_kelly = max_kelly
        self.min_kelly = min_kelly

    def compute_kelly(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> float:
        """计算 Kelly 比例 f*。

        Parameters
        ----------
        win_rate : float
            胜率 (0 ~ 1)
        avg_win : float
            平均盈利百分比（正数，如 4.21 表示 +4.21%）
        avg_loss : float
            平均亏损百分比（正数，如 0.41 表示 -0.41%）

        Returns
        -------
        float
            Kelly 比例，范围 [0, 0.5]
        """
        # 输入校验
        if win_rate <= 0.0 or win_rate >= 1.0:
            logger.debug("Kelly: win_rate=%.4f out of (0,1), returning 0", win_rate)
            return self.min_kelly

        if avg_win <= 0.0 or avg_loss <= 0.0:
            logger.debug("Kelly: avg_win=%.4f or avg_loss=%.4f <= 0, returning 0", avg_win, avg_loss)
            return self.min_kelly

        # 盈亏比
        b = avg_win / avg_loss

        if b <= 0.0:
            logger.debug("Kelly: b=%.4f <= 0, returning 0", b)
            return self.min_kelly

        # Kelly 公式
        p = win_rate
        q = 1.0 - p
        f_star = (p * b - q) / b

        # 裁切
        f_star = np.clip(f_star, self.min_kelly, self.max_kelly)
        return float(round(f_star, 4))

    def __repr__(self) -> str:
        return f"KellyPositionSizer(max={self.max_kelly}, min={self.min_kelly})"


# ---------------------------------------------------------------------------
# SettlementEngine
# ---------------------------------------------------------------------------

class SettlementEngine:
    """结算引擎 — 结算/胜率统计/自适应配额。

    win_rate_data.json 结构:
    {
        "by_strategy": {
            "breakthrough": {
                "trades": 100, "wins": 55,
                "avg_win": 4.21, "avg_loss": 0.41,
                "total_score": 42.5,
                "ev": 0.425,
                "kelly": 0.40,
                "sortino": 1.5,
                "scores": [2.1, -0.3, 1.5, ...],  # 回测用
                "sell_dates": ["2026-06-17", ...],
            },
            ...
        },
        "weekly_scores": {
            "2026-W25": 15.2,
            ...
        }
    }
    """

    DEFAULT_WIN_RATE_PATH = "win_rate_data.json"

    def __init__(
        self,
        win_rate_path: Optional[str] = None,
        kelly_sizer: Optional[KellyPositionSizer] = None,
        risk_free_rate: float = 0.0,
    ):
        self.win_rate_path = win_rate_path or self.DEFAULT_WIN_RATE_PATH
        self.kelly_sizer = kelly_sizer or KellyPositionSizer()
        self.risk_free_rate = risk_free_rate
        self._data: Dict[str, Any] = self._init_data()

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    @staticmethod
    def _init_data() -> Dict[str, Any]:
        return {
            "by_strategy": {},
            "weekly_scores": {},
        }

    def load_win_rate(self, path: Optional[str] = None) -> Dict[str, Any]:
        """从 JSON 文件加载 win_rate 数据。

        Parameters
        ----------
        path : str, optional
            若为 None 则用 self.win_rate_path。

        Returns
        -------
        Dict[str, Any]
            by_strategy dict
        """
        load_path = path or self.win_rate_path
        # 尝试主文件
        loaded = False
        if Path(load_path).exists():
            try:
                with open(load_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                loaded = True
                logger.info("Loaded win_rate data from %s", load_path)
            except Exception as exc:
                logger.warning("Failed to load %s: %s, trying backup", load_path, exc)

        # fallback: 尝试 .bak
        if not loaded:
            bak_path = load_path + ".bak"
            if Path(bak_path).exists():
                try:
                    with open(bak_path, "r", encoding="utf-8") as f:
                        self._data = json.load(f)
                    loaded = True
                    logger.info("Loaded win_rate data from backup %s", bak_path)
                except Exception as exc:
                    logger.warning("Failed to load backup %s: %s", bak_path, exc)

        if not loaded:
            self._data = self._init_data()
            logger.info("Initialized fresh win_rate data (no file found)")

        # 确保 by_strategy 存在
        if "by_strategy" not in self._data:
            self._data["by_strategy"] = {}
        if "weekly_scores" not in self._data:
            self._data["weekly_scores"] = {}

        return self._data["by_strategy"]

    def save_win_rate(self, path: Optional[str] = None) -> None:
        """保存 win_rate 数据到 JSON，同时写 .bak 备份。"""
        save_path = path or self.win_rate_path
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

        # 写主文件
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

        # 写备份
        bak_path = save_path + ".bak"
        try:
            with open(bak_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Failed to write backup %s: %s", bak_path, exc)

        logger.info("Saved win_rate data to %s (backup: %s)", save_path, bak_path)

    # ------------------------------------------------------------------
    # 结算
    # ------------------------------------------------------------------

    def record_settlement(
        self,
        code: str,
        strategy: str,
        buy_price: float,
        sell_price: float,
        sell_date: Optional[str] = None,
    ) -> float:
        """记录一笔交易的结算结果。

        计分制: win = ret > 0
                score = ret (1% = 1 分)

        Parameters
        ----------
        code : str
            股票代码
        strategy : str
            策略名（breakthrough / momentum / oversold）
        buy_price : float
            买入价格
        sell_price : float
            卖出价格
        sell_date : str, optional
            卖出日期，默认今天

        Returns
        -------
        float
            本次收益率（百分比，如 2.1 表示 +2.1%）
        """
        if buy_price <= 0:
            logger.error("Invalid buy_price=%.2f for %s", buy_price, code)
            return 0.0

        ret = (sell_price - buy_price) / buy_price * 100.0  # %
        score = round(ret, 1)  # 1% = 1 分
        is_win = ret > 0

        # 确保策略存在
        by_strategy = self._data["by_strategy"]
        if strategy not in by_strategy:
            by_strategy[strategy] = self._init_strategy_stats()

        stats = by_strategy[strategy]
        stats["trades"] += 1
        stats["scores"].append(score)
        stats["total_score"] = round(sum(stats["scores"]), 1)

        if is_win:
            stats["wins"] += 1

        # 更新 sell_dates
        if sell_date is None:
            sell_date = date.today().isoformat()
        stats["sell_dates"].append(sell_date)

        # 更新每周得分
        week_key = self._date_to_week(sell_date)
        self._data["weekly_scores"][week_key] = (
            self._data["weekly_scores"].get(week_key, 0.0) + score
        )

        # 重新计算统计
        self.compute_stats(strategy)

        logger.info(
            "Settlement: %s | %s | buy=%.2f sell=%.2f | ret=%.2f%% | win=%s | score=%.1f",
            code, strategy, buy_price, sell_price, ret, is_win, score,
        )

        # 保存
        self.save_win_rate()
        return ret

    @staticmethod
    def _init_strategy_stats() -> Dict[str, Any]:
        return {
            "trades": 0,
            "wins": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "total_score": 0.0,
            "ev": 0.0,
            "kelly": 0.0,
            "sortino": 0.0,
            "scores": [],
            "sell_dates": [],
        }

    @staticmethod
    def _date_to_week(date_str: str) -> str:
        """将 '2026-06-18' 转为 '2026-W25' 格式。"""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            iso = dt.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        except (ValueError, TypeError):
            return date_str

    # ------------------------------------------------------------------
    # 统计计算
    # ------------------------------------------------------------------

    def compute_stats(self, strategy: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """计算（或重算）各策略的统计指标。

        Parameters
        ----------
        strategy : str, optional
            若提供则只重算该策略，否则重算全部。

        Returns
        -------
        Dict[str, Dict[str, Any]]
            by_strategy 字典（含计算后的统计字段）
        """
        by_strategy = self._data["by_strategy"]

        targets = [strategy] if strategy else list(by_strategy.keys())

        for name in targets:
            stats = by_strategy.get(name)
            if stats is None or stats["trades"] == 0:
                continue

            scores = np.array(stats["scores"], dtype=float)
            wins = scores[scores > 0] if len(scores[scores > 0]) > 0 else np.array([0.0])
            losses = scores[scores <= 0] if len(scores[scores <= 0]) > 0 else np.array([0.0])

            trades = len(scores)
            win_count = len(wins)

            # 胜率
            win_rate = win_count / trades if trades > 0 else 0.0

            # 平均盈亏
            avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
            avg_loss = float(abs(np.mean(losses))) if len(losses) > 0 else 0.0

            # EV (期望值)
            ev = float(np.mean(scores)) if trades > 0 else 0.0

            # Kelly
            kelly_value = self.kelly_sizer.compute_kelly(win_rate, avg_win, avg_loss)

            # Sortino: 仅用负收益（损失）的下行标准差
            downside = scores[scores < 0]
            if len(downside) > 0:
                downside_std = float(np.std(downside, ddof=1))
                sortino = (ev - self.risk_free_rate) / downside_std if downside_std > 0 else 0.0
            else:
                sortino = 10.0  # 没有亏损，Sortino 极高

            # 更新
            stats["win_rate"] = round(win_rate, 4)
            stats["avg_win"] = round(avg_win, 4)
            stats["avg_loss"] = round(avg_loss, 4)
            stats["total_score"] = round(float(np.sum(scores)), 1)
            stats["ev"] = round(ev, 4)
            stats["kelly"] = round(kelly_value, 4)
            stats["sortino"] = round(sortino, 4)

        return by_strategy

    def get_strategy_stats(self, strategy: str) -> Dict[str, Any]:
        """获取单个策略的统计。"""
        by_strategy = self._data["by_strategy"]
        stats = by_strategy.get(strategy)
        if stats is None:
            return self._init_strategy_stats()
        return stats

    # ------------------------------------------------------------------
    # 自适应配额 / 权重
    # ------------------------------------------------------------------

    def adaptive_quota(self, strategy: str) -> int:
        """根据 EV 和 Kelly 计算自适应配额。

        公式: quota = 2 + round(ev) + round(kelly * 5)

        Parameters
        ----------
        strategy : str
            策略名

        Returns
        -------
        int
            建议配额（至少 0）
        """
        stats = self.get_strategy_stats(strategy)
        ev = stats.get("ev", 0.0)
        kelly = stats.get("kelly", 0.0)
        quota = 2 + round(ev) + round(kelly * 5)
        return max(0, quota)

    def strategy_weight(self, strategy: str) -> float:
        """计算策略仓位权重。

        公式: weight = Kelly * 2
        上限 50%, 下限 10%

        Parameters
        ----------
        strategy : str
            策略名

        Returns
        -------
        float
            权重 (0.1 ~ 0.5)
        """
        stats = self.get_strategy_stats(strategy)
        kelly = stats.get("kelly", 0.0)
        weight = kelly * 2.0
        return float(np.clip(weight, 0.1, 0.5))

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------

    def summary(self) -> pd.DataFrame:
        """返回所有策略的统计汇总 DataFrame。"""
        rows = []
        by_strategy = self._data["by_strategy"]
        for name, stats in by_strategy.items():
            rows.append({
                "strategy": name,
                "trades": stats.get("trades", 0),
                "wins": stats.get("wins", 0),
                "win_rate": stats.get("win_rate", 0.0),
                "avg_win": stats.get("avg_win", 0.0),
                "avg_loss": stats.get("avg_loss", 0.0),
                "total_score": stats.get("total_score", 0.0),
                "ev": stats.get("ev", 0.0),
                "kelly": stats.get("kelly", 0.0),
                "sortino": stats.get("sortino", 0.0),
                "adaptive_quota": self.adaptive_quota(name),
                "weight": self.strategy_weight(name),
            })
        return pd.DataFrame(rows)

    def __repr__(self) -> str:
        n_strats = len(self._data.get("by_strategy", {}))
        return f"SettlementEngine(strategies={n_strats}, path='{self.win_rate_path}')"
