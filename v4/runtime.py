"""V4 decision facade placed behind the existing V3 automation entrypoints."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Iterable, List

from .audit import save_runtime_state
from .contracts import PIPELINE_ID, SYSTEM_VERSION
from .execution import TradingClock
from .feature_store import LiveFeatureStore
from .model_registry import PublishedModelRegistry
from .readiness import ResearchReadiness


class V4Runtime:
    """Evaluate candidates without changing external scheduler contracts."""

    SCHEDULER_CONTRACT = [
        "v3/scripts/afternoon_push.py",
        "v3/scripts/morning_push.py",
        "v3/scripts/watchlist_scan.py",
        "main.py v3-afternoon",
        "main.py v3-morning",
        "main.py sim-buy",
        "main.py sim-sell",
    ]

    def __init__(self):
        self.readiness = ResearchReadiness().evaluate()
        self.model_registry = PublishedModelRegistry()

    @staticmethod
    def _market_score(market_state: Dict[str, Any]) -> float:
        breadth = float(market_state.get("advance_ratio", 0.5) or 0.5)
        composite = float(market_state.get("composite", 0.0) or 0.0)
        value = 0.60 * ((breadth - 0.5) / 0.20) + 0.40 * math.tanh(
            composite / 5.0
        )
        return max(-1.0, min(1.0, value))

    @staticmethod
    def _shadow_confidence(score: float, market_score: float) -> float:
        raw = (score - 80.0) / 7.5 + 0.65 * market_score
        return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, raw))))

    def system_state(self, market_state: Dict[str, Any] | None = None) -> Dict[str, Any]:
        market = market_state or {}
        return {
            "system_version": SYSTEM_VERSION,
            "pipeline_id": PIPELINE_ID,
            "readiness": self.readiness,
            "market_score": self._market_score(market),
            "market_mode": market.get("mode_label", "neutral"),
            "clock": {
                "buy": TradingClock.action_status("buy").to_dict(),
                "sell": TradingClock.action_status("sell").to_dict(),
            },
            "scheduler_contract_preserved": True,
            "scheduler_entrypoints": list(self.SCHEDULER_CONTRACT),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def evaluate_candidates(
        self,
        candidates: Iterable[Dict[str, Any]],
        market_state: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        market = market_state or {}
        market_mode = market.get("mode_label", "neutral")
        market_score = self._market_score(market)
        buy_status = TradingClock.action_status("buy")
        evaluated: List[Dict[str, Any]] = []

        for index, candidate in enumerate(candidates, start=1):
            item = dict(candidate)
            score = float(item.get("final_score", item.get("score", 0.0)) or 0.0)
            rank = int(item.get("rank", index) or index)
            shadow_confidence = self._shadow_confidence(score, market_score)
            if item.get("predicted_positive_probability") is None:
                if not item.get("v4_features"):
                    item["v4_features"] = LiveFeatureStore.get(item.get("code", ""))
                model_prediction = self.model_registry.predict(
                    item.get("v4_features", {})
                )
                if model_prediction:
                    item.update(model_prediction)
            blocks = []
            if not self.readiness.get("trade_enabled", False):
                blocks.append("研究准入未通过")
            if not buy_status.allowed:
                blocks.append(buy_status.reason)
            if market_mode == "risk_off":
                blocks.append("市场风险关闭")
            if rank != 1:
                blocks.append("精度优先仅允许Top1")
            if score < 80.0:
                blocks.append("旧评分低于80")
            if item.get("is_mock"):
                blocks.append("模拟候选")
            if float(item.get("price", 0.0) or 0.0) <= 0:
                blocks.append("价格无效")
            if not TradingClock.quote_is_fresh(item.get("quote_time")):
                blocks.append("行情时间戳缺失或过期")

            positive_probability = item.get("predicted_positive_probability")
            loss_probability = item.get("predicted_large_loss_probability")
            if positive_probability is not None and float(positive_probability) < 0.55:
                blocks.append("净盈利概率不足")
            if loss_probability is not None and float(loss_probability) > 0.15:
                blocks.append("大亏概率过高")
            if self.readiness.get("trade_enabled") and positive_probability is None:
                blocks.append(
                    self.model_registry.last_prediction_error
                    or self.model_registry.error
                    or "生产模型未产生预测"
                )

            item.update(
                {
                    "rank": rank,
                    "v4_status": self.readiness.get("status", "research_locked"),
                    "v4_tradable": not blocks,
                    "v4_decision": "允许模拟" if not blocks else "观察/空仓",
                    "v4_block_reasons": blocks,
                    "v4_shadow_confidence": round(shadow_confidence, 4),
                    "v4_market_score": round(market_score, 4),
                    "v4_pipeline": PIPELINE_ID,
                    "v4_model_probability_available": positive_probability is not None,
                }
            )
            evaluated.append(item)

        snapshot = self.system_state(market)
        snapshot["candidates"] = evaluated
        save_runtime_state(snapshot)
        return evaluated
