"""V4-native, causal candidate generation for observation and research.

This module owns candidate creation while the production model is locked.  It
uses the same transparent point-in-time baseline features as research, never
the legacy V3 chase/pullback scorers.  Research ranking is not a calibrated
probability and can never bypass the V4 readiness or execution gates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .market_contracts import MarketSnapshotV1
from .snapshot_frame import snapshot_frame

from decision_policy import adaptive_strategy_decision
from market_universe import is_eligible_a_share
from phase1.overnight.dataset import FEATURE_COLUMNS
from strategy_spec import DEFAULT_SPEC, TradeCostModel
from .execution import TradingClock
from .feature_store import LiveFeatureStore
from .market import classify_sector


ROOT = Path(__file__).resolve().parent.parent
CONTEXT_PATH = ROOT / "phase1" / "data" / "overnight" / "live_feature_context.csv.gz"
CONTEXT_META_PATH = CONTEXT_PATH.with_suffix(CONTEXT_PATH.suffix + ".meta.json")
RESEARCH_RANK_VERSION = "v4-causal-rule-rank-v1"
CONFIRMATION_SCORE_VERSION = "v4-base-plus-confirm-delta-v1"

# Must stay aligned with phase1.overnight.backtesting.add_rule_score.  These
# are fixed, transparent research weights, not fitted production parameters.
RULE_WEIGHTS = {
    "signal_return": 0.20,
    "signal_close_position": 0.15,
    "volume_ratio_20": 0.10,
    "ret_5d": 0.15,
    "price_to_ma20": 0.10,
    "overnight_mean_20": 0.15,
    "overnight_hit_1pct_20": 0.15,
}


def _percentile(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.rank(pct=True, method="average").fillna(0.5)


class V4CandidateSelector:
    """Generate V4 candidates from the complete eligible live universe."""

    def __init__(self, context_path: Optional[Path] = None):
        self.context_path = Path(context_path) if context_path else CONTEXT_PATH
        self.context_meta_path = self.context_path.with_suffix(
            self.context_path.suffix + ".meta.json"
        )
        self.last_diagnostics: Dict[str, Any] = {
            "status": "not_run",
            "source": RESEARCH_RANK_VERSION,
        }

    def _load_context(self) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        try:
            metadata = json.loads(self.context_meta_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict) or not metadata.get("strict_context_ready"):
                return pd.DataFrame(), metadata if isinstance(metadata, dict) else {}
            context = pd.read_csv(self.context_path, dtype={"code": str})
            required = {
                "code", "context_date", "context_prev_close", "volume_mean_20",
                "ma5_base", "ma10_base", "ma20_base", "ret_1d", "ret_3d",
                "ret_5d", "ret_10d", "ret_20d", "volatility_20",
                "overnight_mean_20", "overnight_hit_1pct_20",
            }
            if not required.issubset(context.columns):
                return pd.DataFrame(), metadata
            context["code"] = context["code"].astype(str).str.zfill(6)
            context = context.drop_duplicates("code", keep="last")
            return context, metadata
        except (OSError, TypeError, ValueError):
            return pd.DataFrame(), {}

    @staticmethod
    def _eligible_quotes(
        snapshot: MarketSnapshotV1, *, reference_time=None
    ) -> pd.DataFrame:
        frame = snapshot_frame(snapshot)
        if frame.empty:
            return pd.DataFrame()
        required = {"code", "name", "price", "quote_time"}
        if not required.issubset(frame.columns):
            return pd.DataFrame()
        frame["code"] = frame["code"].astype(str).str.zfill(6)
        frame = frame[frame["code"].map(is_eligible_a_share)].copy()
        frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
        frame = frame[
            frame["price"].between(
                DEFAULT_SPEC.minimum_stock_price,
                DEFAULT_SPEC.maximum_stock_price,
                inclusive="both",
            )
            & ~frame["name"].astype(str).str.contains("ST|退", case=False, na=False)
            & frame["quote_time"].map(
                lambda value: TradingClock.quote_is_fresh(value, now=reference_time)
            )
        ].drop_duplicates("code", keep="last")
        return frame

    def _observation_features(
        self, quotes: pd.DataFrame, market_state: Dict[str, Any]
    ) -> Tuple[pd.DataFrame, str]:
        context, metadata = self._load_context()
        if context.empty:
            return pd.DataFrame(), "上一交易日冻结上下文缺失或未就绪"
        required = {"prev_close", "open", "high", "low", "volume"}
        if not required.issubset(quotes.columns):
            return pd.DataFrame(), "行情字段不足，无法生成V4观察特征"
        live = quotes.copy()
        for column in ("price", "prev_close", "open", "high", "low", "volume"):
            live[column] = pd.to_numeric(live[column], errors="coerce")
        merged = live.merge(context, on="code", how="inner")
        if merged.empty:
            return merged, "行情与冻结上下文无交集"
        previous_difference = (
            merged["prev_close"] / merged["context_prev_close"] - 1.0
        ).abs()
        merged = merged[previous_difference <= 0.005].copy()
        if merged.empty:
            return merged, "前收盘与冻结上下文不一致"
        effective_open = merged["open"].where(merged["open"].gt(0), merged["price"])
        effective_high = merged[["high", "price"]].max(axis=1)
        positive_low = merged["low"].where(merged["low"].gt(0), merged["price"])
        effective_low = pd.concat([positive_low, merged["price"]], axis=1).min(axis=1)
        merged["signal_return"] = merged["price"] / merged["prev_close"] - 1.0
        merged["gap_return"] = effective_open / merged["prev_close"] - 1.0
        merged["signal_range"] = (effective_high - effective_low) / merged["prev_close"]
        span = effective_high - effective_low
        merged["signal_close_position"] = np.where(
            span > 0, (merged["price"] - effective_low) / span, 0.5
        )
        merged["volume_ratio_20"] = merged["volume"] / merged["volume_mean_20"]
        for days in (5, 10, 20):
            merged[f"price_to_ma{days}"] = merged["price"] / merged[f"ma{days}_base"] - 1.0
        merged["market_mean_signal_return"] = float(
            market_state.get("market_mean_signal_return", 0.0) or 0.0
        )
        merged["market_breadth"] = float(
            market_state.get("advance_ratio", 0.5) or 0.5
        )
        merged["market_mean_gap"] = float(
            market_state.get("market_mean_gap", 0.0) or 0.0
        )
        merged = merged.replace([np.inf, -np.inf], np.nan).dropna(
            subset=FEATURE_COLUMNS
        )
        expected_previous = str(metadata.get("expected_previous_session", ""))
        if expected_previous and not merged["context_date"].astype(str).eq(expected_previous).all():
            return pd.DataFrame(), "冻结上下文日期血缘不一致"
        return merged, ""

    @staticmethod
    def _frozen_features(quotes: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
        features = LiveFeatureStore.load_all(maximum_age_seconds=180)
        if not features:
            return pd.DataFrame(), "14:49冻结特征缺失或过期"
        feature_frame = pd.DataFrame.from_dict(features, orient="index")
        feature_frame.index = feature_frame.index.astype(str).str.zfill(6)
        joined = quotes.set_index("code", drop=False).join(
            feature_frame.reindex(columns=FEATURE_COLUMNS), how="inner", rsuffix="_feature"
        )
        joined = joined.replace([np.inf, -np.inf], np.nan).dropna(
            subset=FEATURE_COLUMNS
        )
        return joined.reset_index(drop=True), "" if not joined.empty else "冻结特征与确认行情无交集"

    @staticmethod
    def _score(frame: pd.DataFrame) -> pd.DataFrame:
        scored = frame.copy()
        scored["v4_research_rule_score"] = 0.0
        for feature, weight in RULE_WEIGHTS.items():
            scored["v4_research_rule_score"] += _percentile(scored[feature]) * weight
        momentum = (
            _percentile(scored["signal_return"])
            + _percentile(scored["ret_5d"])
            + _percentile(scored["signal_close_position"])
        ) / 3.0
        pullback = (
            _percentile(-scored["price_to_ma10"].abs())
            + _percentile(scored["ret_20d"])
            + _percentile(-scored["signal_return"].abs())
        ) / 3.0
        scored["strategy_key"] = np.where(
            momentum >= pullback, "momentum", "pullback"
        )
        scored["strategy"] = np.where(
            scored["strategy_key"].eq("momentum"),
            "V4强势延续",
            "V4回撤修复",
        )
        return scored

    @staticmethod
    def _apply_confirmation_score(
        frame: pd.DataFrame, morning_candidates: list[Dict[str, Any]]
    ) -> pd.DataFrame:
        """Keep the full-universe morning percentile and add a fixed live delta."""

        morning = {
            str(item.get("code", "")).zfill(6): item
            for item in morning_candidates
            if item.get("code")
        }
        scored = frame.copy()
        scored["code"] = scored["code"].astype(str).str.zfill(6)
        scored = scored[scored["code"].isin(morning)].copy()
        if scored.empty:
            return scored
        scored["base_score"] = scored["code"].map(
            lambda code: float(morning[code].get(
                "base_score", morning[code].get("score", 0.0)
            ) or 0.0)
        )
        morning_signal = scored["code"].map(
            lambda code: float(morning[code].get("v4_features", {}).get(
                "signal_return", 0.0
            ) or 0.0)
        )
        morning_close = scored["code"].map(
            lambda code: float(morning[code].get("v4_features", {}).get(
                "signal_close_position", 0.5
            ) or 0.5)
        )
        morning_volume = scored["code"].map(
            lambda code: max(0.0, float(morning[code].get("v4_features", {}).get(
                "volume_ratio_20", 0.0
            ) or 0.0))
        )
        return_delta_points = (
            (pd.to_numeric(scored["signal_return"], errors="coerce") - morning_signal)
            * 100.0 * 1.5
        )
        close_delta_points = (
            pd.to_numeric(scored["signal_close_position"], errors="coerce")
            - morning_close
        ) * 5.0
        current_volume = pd.to_numeric(
            scored["volume_ratio_20"], errors="coerce"
        ).clip(lower=0.0)
        volume_delta_points = (
            np.log1p(current_volume) - np.log1p(morning_volume)
        ).clip(-1.0, 1.0)
        scored["confirm_delta"] = (
            return_delta_points + close_delta_points + volume_delta_points
        ).clip(-5.0, 5.0).round(4)
        scored["decision_score"] = (
            scored["base_score"] + scored["confirm_delta"]
        ).clip(0.0, 100.0).round(4)
        scored["v4_research_rule_score"] = scored["decision_score"] / 100.0
        scored["strategy_key"] = scored["code"].map(
            lambda code: morning[code].get("strategy_key", "momentum")
        )
        scored["strategy"] = scored["code"].map(
            lambda code: morning[code].get("strategy", "V4强势延续")
        )
        return scored

    def select_research(
        self,
        snapshot: MarketSnapshotV1,
        market_state: Dict[str, Any],
        *,
        require_frozen_features: bool,
        maximum_candidates: int = 5,
        allowed_codes: Optional[set[str]] = None,
        morning_candidates: Optional[list[Dict[str, Any]]] = None,
        reference_time=None,
    ) -> list[Dict[str, Any]]:
        eligible = self._eligible_quotes(snapshot, reference_time=reference_time)
        if allowed_codes is not None:
            normalized = {str(code).zfill(6) for code in allowed_codes}
            eligible = eligible[eligible["code"].isin(normalized)].copy()
        stage = "confirmation_1450" if require_frozen_features else "morning_observation"
        paper_market_fallback = bool(
            require_frozen_features
            and allowed_codes is not None
            and market_state.get("snapshot_complete") is True
            and float(market_state.get("quote_coverage", 0.0) or 0.0) >= 0.95
            and not eligible.empty
        )
        if market_state.get("data_valid") is not True and not paper_market_fallback:
            self.last_diagnostics = {
                "status": "blocked",
                "reason": "全市场行情覆盖或时效未通过",
                "source": RESEARCH_RANK_VERSION,
                "stage": stage,
                "eligible_quotes": int(len(eligible)),
            }
            return []
        if eligible.empty:
            self.last_diagnostics = {
                "status": "blocked",
                "reason": "没有新鲜且合格的A股行情",
                "source": RESEARCH_RANK_VERSION,
                "stage": stage,
                "eligible_quotes": 0,
            }
            return []
        if require_frozen_features:
            feature_frame, error = self._frozen_features(eligible)
            feature_source = "v4_frozen_1449"
            # A failed full-market strict archive must remain excluded from the
            # training dataset, but it must not erase the already locked 09:25
            # observation pool.  Recompute only that small pool from the live
            # 14:50 quote and previous-session frozen context.  This is causal,
            # explicitly paper-only, and never satisfies production readiness.
            if feature_frame.empty and allowed_codes is not None:
                feature_frame, fallback_error = self._observation_features(
                    eligible, market_state
                )
                if not feature_frame.empty:
                    error = ""
                    feature_source = "v4_live_1450_mother_pool_paper_only"
                else:
                    error = fallback_error or error
        else:
            feature_frame, error = self._observation_features(eligible, market_state)
            feature_source = "v4_previous_session_context"
        if feature_frame.empty:
            self.last_diagnostics = {
                "status": "blocked",
                "reason": error or "V4特征不可用",
                "source": RESEARCH_RANK_VERSION,
                "stage": stage,
                "eligible_quotes": int(len(eligible)),
            }
            return []

        limit_rate = feature_frame["code"].map(
            lambda code: 0.20 if str(code).startswith("30") else 0.10
        )
        feature_frame = feature_frame[
            feature_frame["signal_return"] < (limit_rate - 0.005)
        ].copy()
        if feature_frame.empty:
            self.last_diagnostics = {
                "status": "empty",
                "reason": "所有股票均触发不可追价边界",
                "source": RESEARCH_RANK_VERSION,
                "stage": stage,
            }
            return []

        if require_frozen_features and morning_candidates is not None:
            scored = self._apply_confirmation_score(feature_frame, morning_candidates)
        else:
            scored = self._score(feature_frame)
            scored["base_score"] = scored["v4_research_rule_score"] * 100.0
            scored["confirm_delta"] = 0.0
            scored["decision_score"] = scored["base_score"]
        policy_market = dict(market_state)
        if paper_market_fallback:
            policy_market["mode_label"] = market_state.get(
                "observed_mode_label", "neutral"
            )
        policy = adaptive_strategy_decision(policy_market)
        allowed_keys = set(policy.get("candidate_strategy_keys", []))
        if allowed_keys:
            scored = scored[scored["strategy_key"].isin(allowed_keys)].copy()
        elif policy.get("key") == "observe" and require_frozen_features:
            scored = scored.iloc[0:0].copy()
        if scored.empty:
            self.last_diagnostics = {
                "status": "empty",
                "reason": "V4市场路由选择空仓",
                "source": RESEARCH_RANK_VERSION,
                "stage": stage,
                "policy": policy,
            }
            return []

        scored["_amount"] = (
            pd.to_numeric(scored["amount"], errors="coerce").fillna(0.0)
            if "amount" in scored.columns
            else pd.Series(0.0, index=scored.index)
        )
        scored = scored.sort_values(
            ["decision_score", "_amount", "code"],
            ascending=[False, False, True],
        ).head(max(1, int(maximum_candidates)))
        cost_model = TradeCostModel(DEFAULT_SPEC)
        candidates = []
        for rank, (_, row) in enumerate(scored.iterrows(), start=1):
            ask_value = pd.to_numeric(row.get("ask1"), errors="coerce")
            ask1 = float(ask_value) if pd.notna(ask_value) else 0.0
            reference = ask1 if ask1 > 0 else float(row["price"])
            vector = {
                name: float(row[name]) for name in FEATURE_COLUMNS
            }
            candidates.append(
                {
                    "code": str(row["code"]).zfill(6),
                    "name": str(row.get("name", "")),
                    "rank": rank,
                    "price": reference,
                    "last_price": float(row["price"]),
                    "buy_price": round(cost_model.buy_fill_price(reference), 3),
                    "quote_time": row.get("quote_time"),
                    "change_pct": float(row.get("change_pct", row.get("pct_chg", 0.0)) or 0.0),
                    "pct_chg": float(row.get("change_pct", row.get("pct_chg", 0.0)) or 0.0),
                    "base_score": round(float(row["base_score"]), 4),
                    "confirm_delta": round(float(row["confirm_delta"]), 4),
                    "decision_score": round(float(row["decision_score"]), 4),
                    "score": round(float(row["decision_score"]), 2),
                    "final_score": round(float(row["decision_score"]), 2),
                    "v4_research_rule_score": round(float(row["v4_research_rule_score"]), 6),
                    "strategy": str(row["strategy"]),
                    "strategy_key": str(row["strategy_key"]),
                    "sector": classify_sector(str(row.get("name", ""))),
                    "amount_yi": round(float(row.get("amount", 0.0) or 0.0) / 1e8, 2),
                    "close_position": round(float(row["signal_close_position"]), 4),
                    "volume_ratio": round(float(row["volume_ratio_20"]), 4),
                    "near_5d_return": round(float(row["ret_5d"]) * 100.0, 3),
                    "dist_to_ma10": round(float(row["price_to_ma10"]) * 100.0, 3),
                    "overnight_mean_20": round(float(row["overnight_mean_20"]), 6),
                    "overnight_hit_1pct_20": round(float(row["overnight_hit_1pct_20"]), 6),
                    "execution_price_source": "ask1" if ask1 > 0 else "last_observation_only",
                    "selection_stage": stage,
                    "candidate_source": RESEARCH_RANK_VERSION,
                    "score_version": (
                        CONFIRMATION_SCORE_VERSION if require_frozen_features
                        else RESEARCH_RANK_VERSION
                    ),
                    "feature_source": feature_source,
                    "v4_candidate_origin": "V4",
                    "v4_research_ranked": True,
                    "v4_paper_market_valid": bool(
                        market_state.get("data_valid") is True
                        or paper_market_fallback
                    ),
                    "v4_paper_market_mode": policy_market.get(
                        "mode_label", market_state.get("mode_label", "neutral")
                    ),
                    "v4_features": vector,
                }
            )
        self.last_diagnostics = {
            "status": "ranked",
            "reason": "V4全市场因果规则完成排序",
            "source": RESEARCH_RANK_VERSION,
            "feature_source": feature_source,
            "stage": stage,
            "eligible_quotes": int(len(eligible)),
            "feature_rows": int(len(feature_frame)),
            "candidates": int(len(candidates)),
            "policy": policy,
            "research_only": True,
            "strict_feature_archive_available": feature_source == "v4_frozen_1449",
            "paper_only_fallback": feature_source == "v4_live_1450_mother_pool_paper_only",
            "paper_market_fallback": paper_market_fallback,
        }
        return candidates
