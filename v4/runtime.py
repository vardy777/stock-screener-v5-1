"""V4 decision engine behind stable legacy-named automation entrypoints."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Iterable, List

import pandas as pd

from decision_policy import market_regime_score
from market_universe import is_eligible_a_share
from phase1.overnight.dataset import FEATURE_COLUMNS
from .audit import save_runtime_state
from .contracts import PIPELINE_ID, SYSTEM_VERSION
from .execution import TradingClock
from .feature_store import LiveFeatureStore
from .model_registry import PublishedModelRegistry
from .readiness import ResearchReadiness
from .selection import RESEARCH_RANK_VERSION, V4CandidateSelector


class V4Runtime:
    """Evaluate candidates without changing external scheduler contracts."""

    SCHEDULER_CONTRACT = [
        "v4/scripts/afternoon_push.py",
        "v4/scripts/morning_push.py",
        "v4/scripts/paper_trade.py buy",
        "v4/scripts/paper_trade.py sell",
        "python -m v4.dashboard",
    ]

    def __init__(self):
        self.readiness = ResearchReadiness().evaluate()
        self.model_registry = PublishedModelRegistry()
        self.candidate_selector = V4CandidateSelector()
        self.last_selection: Dict[str, Any] = {
            "status": "not_run",
            "source": RESEARCH_RANK_VERSION,
        }

    @property
    def production_enabled(self) -> bool:
        return bool(
            self.readiness.get("trade_enabled", False)
            and self.model_registry.available
        )

    @staticmethod
    def _market_score(market_state: Dict[str, Any]) -> float:
        if market_state.get("regime_score") is not None:
            return max(-1.0, min(1.0, float(market_state["regime_score"])))
        return market_regime_score(
            float(market_state.get("advance_ratio", 0.5) or 0.5),
            float(market_state.get("market_mean_signal_return", 0.0) or 0.0),
            float(market_state.get("market_mean_gap", 0.0) or 0.0),
        )

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
            "candidate_engine": "V4",
            "selection": dict(getattr(self, "last_selection", {"status": "not_run"})),
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
        production_available = self.production_enabled
        evaluated: List[Dict[str, Any]] = []

        for index, candidate in enumerate(candidates, start=1):
            item = dict(candidate)
            score = float(item.get("final_score", item.get("score", 0.0)) or 0.0)
            rank = int(item.get("rank", index) or index)
            shadow_confidence = self._shadow_confidence(score, market_score)
            model_ranked = bool(
                production_available
                and item.get("candidate_source") == "v4_published_model"
            )
            policy = self.model_registry.policy if model_ranked else {}
            if model_ranked:
                # Model-owned fields are always overwritten in production;
                # never trust a cached or caller-supplied probability.
                model_prediction = self.model_registry.predict(
                    item.get("v4_features", {})
                )
                for key in (
                    "predicted_return",
                    "predicted_positive_probability",
                    "predicted_hit_probability",
                    "predicted_large_loss_probability",
                ):
                    item.pop(key, None)
                if model_prediction:
                    item.update(model_prediction)
            blocks = []
            if not self.readiness.get("trade_enabled", False):
                blocks.append("研究准入未通过")
            if not production_available:
                blocks.append("V4生产模型尚未发布")
            elif buy_status.allowed and not model_ranked:
                blocks.append("买入窗口只接受V4生产模型候选")
            if not buy_status.allowed:
                blocks.append(buy_status.reason)
            if market_mode == "risk_off":
                blocks.append("市场风险关闭")
            if market.get("data_valid") is not True:
                blocks.append("全市场状态数据无效或覆盖不足")
            if item.get("v4_candidate_origin") != "V4":
                blocks.append("候选来源不是V4")
            if rank != 1:
                blocks.append("精度优先仅允许Top1")
            if not model_ranked and score < 55.0:
                blocks.append("V4研究基线分低于55")
            if item.get("is_mock"):
                blocks.append("模拟候选")
            if float(item.get("price", 0.0) or 0.0) <= 0:
                blocks.append("价格无效")
            if not TradingClock.quote_is_fresh(item.get("quote_time")):
                blocks.append("行情时间戳缺失或过期")

            paper_blocks = []
            paper_market_mode = item.get("v4_paper_market_mode", market_mode)
            paper_market_valid = bool(
                item.get("v4_paper_market_valid", market.get("data_valid") is True)
            )
            if item.get("selection_stage") != "confirmation_1450":
                paper_blocks.append("仅允14:50确认候选进入模拟观测")
            if item.get("linkage_status") != "confirmed_from_morning_pool":
                paper_blocks.append("未通过09:25母池链路确认")
            if rank != 1:
                paper_blocks.append("模拟观测仅执行Top1")
            if score < 80.0:
                paper_blocks.append("规则分低于80")
            if paper_market_mode == "risk_off" or not paper_market_valid:
                paper_blocks.append("市场风险或数据质量不允许")
            if item.get("v4_candidate_origin") != "V4" or item.get("is_mock"):
                paper_blocks.append("候选来源不合格")
            if not buy_status.allowed:
                paper_blocks.append(buy_status.reason)
            if float(item.get("price", 0.0) or 0.0) <= 0 or not TradingClock.quote_is_fresh(item.get("quote_time")):
                paper_blocks.append("确认价格或时效不合格")

            positive_probability = item.get("predicted_positive_probability")
            loss_probability = item.get("predicted_large_loss_probability")
            predicted_return = item.get("predicted_return")
            minimum_return = policy.get("minimum_predicted_return")
            minimum_positive = policy.get("minimum_positive_probability")
            maximum_loss = policy.get("maximum_large_loss_probability")
            minimum_regime = policy.get("minimum_regime_score")
            if model_ranked and minimum_return is not None and (
                predicted_return is None
                or float(predicted_return) < float(minimum_return)
            ):
                blocks.append("预期净收益不足")
            if positive_probability is not None and minimum_positive is not None and float(positive_probability) < float(minimum_positive):
                blocks.append("净盈利概率不足")
            if loss_probability is not None and maximum_loss is not None and float(loss_probability) > float(maximum_loss):
                blocks.append("大亏概率过高")
            if model_ranked and minimum_regime is not None and market_score < float(minimum_regime):
                blocks.append("市场环境低于生产策略阈值")
            if model_ranked and positive_probability is None:
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
                    "v4_paper_eligible": not paper_blocks,
                    "v4_paper_block_reasons": paper_blocks,
                    "v4_decision": "允许模拟" if not blocks else "观察/空仓",
                    "v4_block_reasons": blocks,
                    "v4_shadow_confidence": round(shadow_confidence, 4),
                    "v4_market_score": round(market_score, 4),
                    "v4_pipeline": PIPELINE_ID,
                    "v4_model_probability_available": positive_probability is not None,
                    "v4_model_ranked": model_ranked,
                    "v4_research_ranked": bool(
                        item.get("v4_research_ranked", not model_ranked)
                    ),
                    "v4_candidate_origin": item.get("v4_candidate_origin", "unknown"),
                }
            )
            evaluated.append(item)

        snapshot = self.system_state(market)
        snapshot["candidates"] = evaluated
        save_runtime_state(snapshot)
        return evaluated

    def evaluate_universe(
        self,
        quotes,
        *,
        fallback_candidates: Iterable[Dict[str, Any]] = (),
        market_state: Dict[str, Any] | None = None,
        allowed_codes: set[str] | None = None,
        morning_candidates: list[Dict[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        """Generate candidates from the complete eligible universe using V4.

        ``fallback_candidates`` remains only as a call-signature compatibility
        shim and is deliberately ignored.  V4 research ranking owns candidates
        while locked; the published model owns 14:50 ranking after release.
        """

        market = market_state or {}
        production_model = self.production_enabled
        _ = fallback_candidates
        buy_status = TradingClock.action_status("buy")
        if not production_model or not buy_status.allowed:
            candidates = self.candidate_selector.select_research(
                quotes,
                market,
                require_frozen_features=bool(buy_status.allowed),
                allowed_codes=allowed_codes,
                morning_candidates=morning_candidates,
            )
            self.last_selection = dict(self.candidate_selector.last_diagnostics)
            return self.evaluate_candidates(candidates, market)
        if quotes is None or getattr(quotes, "empty", True):
            self.last_selection = {
                "status": "blocked",
                "reason": "全市场行情为空",
                "source": "v4_published_model",
                "stage": "confirmation_1450",
            }
            return self.evaluate_candidates([], market)

        features = LiveFeatureStore.load_all(maximum_age_seconds=120)
        if not features:
            self.last_selection = {
                "status": "blocked",
                "reason": "14:49冻结特征缺失或过期",
                "source": "v4_published_model",
                "stage": "confirmation_1450",
            }
            return self.evaluate_candidates([], market)
        quote_frame = quotes.copy()
        required = {"code", "name", "price", "quote_time", "ask1"}
        if not required.issubset(quote_frame.columns):
            self.last_selection = {
                "status": "blocked",
                "reason": "生产排序行情字段不足",
                "source": "v4_published_model",
                "stage": "confirmation_1450",
            }
            return self.evaluate_candidates([], market)
        quote_frame["code"] = quote_frame["code"].astype(str).str.zfill(6)
        if allowed_codes is not None:
            normalized = {str(code).zfill(6) for code in allowed_codes}
            quote_frame = quote_frame[quote_frame["code"].isin(normalized)].copy()
        quote_frame = quote_frame[
            quote_frame["code"].map(is_eligible_a_share)
        ].drop_duplicates("code", keep="last")
        quote_frame["last_price"] = pd.to_numeric(
            quote_frame["price"], errors="coerce"
        )
        quote_frame["ask1"] = pd.to_numeric(
            quote_frame["ask1"], errors="coerce"
        )
        quote_frame = quote_frame[
            quote_frame["ask1"].between(5.0, 200.0, inclusive="both")
            & ~quote_frame["name"].astype(str).str.contains("ST|退", na=False)
            & quote_frame["quote_time"].map(TradingClock.quote_is_fresh)
        ].copy()
        quote_frame = quote_frame[quote_frame["code"].isin(features)]
        if quote_frame.empty:
            self.last_selection = {
                "status": "blocked",
                "reason": "冻结特征与确认行情无交集",
                "source": "v4_published_model",
                "stage": "confirmation_1450",
            }
            return self.evaluate_candidates([], market)

        feature_frame = pd.DataFrame.from_dict(features, orient="index")
        feature_frame.index = feature_frame.index.astype(str).str.zfill(6)
        feature_frame = feature_frame.reindex(quote_frame["code"])
        feature_frame.index = quote_frame.index
        feature_frame = feature_frame.reindex(columns=FEATURE_COLUMNS).apply(
            pd.to_numeric, errors="coerce"
        )
        complete = feature_frame.notna().all(axis=1)
        quote_frame = quote_frame.loc[complete].copy()
        feature_frame = feature_frame.loc[complete]
        if quote_frame.empty:
            self.last_selection = {
                "status": "blocked",
                "reason": "生产特征不完整",
                "source": "v4_published_model",
                "stage": "confirmation_1450",
            }
            return self.evaluate_candidates([], market)

        limit_rate = quote_frame["code"].map(
            lambda code: 0.20 if str(code).startswith("30") else 0.10
        )
        entry_ok = feature_frame["signal_return"] < (limit_rate - 0.005)
        quote_frame = quote_frame.loc[entry_ok].copy()
        feature_frame = feature_frame.loc[entry_ok]
        predictions = self.model_registry.predict_frame(feature_frame)
        if predictions.empty:
            self.last_selection = {
                "status": "blocked",
                "reason": self.model_registry.last_prediction_error or "生产模型未产生预测",
                "source": "v4_published_model",
                "stage": "confirmation_1450",
            }
            return self.evaluate_candidates([], market)

        quote_frame = quote_frame.loc[predictions.index].copy()
        for column in predictions.columns:
            quote_frame[column] = predictions[column]
        score_column = str(
            self.model_registry.policy.get("score_column", "predicted_return")
        )
        if score_column not in quote_frame.columns:
            score_column = "predicted_return"
        quote_frame = quote_frame.sort_values(
            [
                score_column,
                "predicted_positive_probability",
                "predicted_large_loss_probability",
            ],
            ascending=[False, False, True],
        ).head(5)

        candidates = []
        for rank, (row_index, row) in enumerate(quote_frame.iterrows(), start=1):
            vector = feature_frame.loc[row_index].to_dict()
            candidates.append(
                {
                    "code": str(row["code"]).zfill(6),
                    "name": str(row.get("name", "")),
                    "rank": rank,
                    "price": float(row["ask1"]),
                    "last_price": float(row["last_price"]),
                    "quote_time": row.get("quote_time"),
                    "change_pct": float(row.get("change_pct", 0.0) or 0.0),
                    "score": float(
                        row.get("predicted_positive_probability", 0.0)
                    ) * 100.0,
                    "final_score": float(
                        row.get("predicted_positive_probability", 0.0)
                    ) * 100.0,
                    "strategy": "v4_model_top1",
                    "strategy_key": "model",
                    "execution_price_source": "ask1",
                    "v4_features": vector,
                    "candidate_source": "v4_published_model",
                    "feature_source": "v4_frozen_1449",
                    "selection_stage": "confirmation_1450",
                    "v4_candidate_origin": "V4",
                    "v4_research_ranked": False,
                    **{
                        column: float(row[column])
                        for column in predictions.columns
                    },
                }
            )
        self.last_selection = {
            "status": "ranked",
            "reason": "V4已发布模型完成全市场排序",
            "source": "v4_published_model",
            "feature_source": "v4_frozen_1449",
            "stage": "confirmation_1450",
            "eligible_quotes": int(len(quote_frame)),
            "candidates": int(len(candidates)),
            "research_only": False,
        }
        return self.evaluate_candidates(candidates, market)
