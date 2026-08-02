"""Shared market-regime functions used by research and live decisions."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def market_regime_score(
    breadth: float, market_return: float, market_gap: float = 0.0
) -> float:
    """Combine causal full-market inputs into the V4 regime score."""

    breadth_component = _clip((float(breadth) - 0.50) / 0.18, -1.0, 1.0)
    return_component = _clip(float(market_return) / 0.012, -1.0, 1.0)
    gap_component = _clip(float(market_gap) / 0.008, -1.0, 1.0)
    return _clip(
        0.50 * breadth_component
        + 0.35 * return_component
        + 0.15 * gap_component,
        -1.0,
        1.0,
    )


def market_is_risk_off(
    breadth: float, market_return: float, market_gap: float = 0.0
) -> bool:
    return bool(
        market_regime_score(breadth, market_return, market_gap) < -0.35
        or (float(breadth) < 0.42 and float(market_return) < -0.003)
    )


def adaptive_strategy_decision(
    market_state: Mapping[str, Any],
    sentiment: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Route V4 research candidates from the current full-market snapshot.

    The policy is deterministic, causal and owned by V4.  It controls which
    V4 research family may enter the observation ranking, but it never
    overrides readiness, the published model, Top1, clock or risk gates.
    """

    state = market_state or {}
    mood = sentiment or {}
    breadth = float(state.get("advance_ratio", 0.5) or 0.5)
    market_return = float(state.get("market_mean_signal_return", 0.0) or 0.0)
    market_gap = float(state.get("market_mean_gap", 0.0) or 0.0)
    regime = float(
        state.get(
            "regime_score",
            market_regime_score(breadth, market_return, market_gap),
        )
        or 0.0
    )
    coverage = float(
        state.get("fresh_quote_coverage", state.get("quote_coverage", 0.0)) or 0.0
    )
    sentiment_score = float(mood.get("score", state.get("sentiment_score", 5)) or 5)

    common = {
        "basis": "causal_market_heuristic_v1",
        "research_only": True,
        "inputs": {
            "breadth": round(breadth, 4),
            "market_return": round(market_return, 6),
            "market_gap": round(market_gap, 6),
            "regime_score": round(regime, 4),
            "fresh_quote_coverage": round(coverage, 4),
            "sentiment_score": round(sentiment_score, 1),
        },
    }

    if state.get("data_valid") is not True:
        return {
            **common,
            "key": "observe",
            "label": "观望 / 空仓",
            "confidence": 0.0,
            "candidate_strategies": [],
            "candidate_strategy_keys": [],
            "reasons": [
                f"可执行行情覆盖仅{coverage * 100:.1f}%",
                "市场快照未通过时效与覆盖门槛",
            ],
        }

    if state.get("mode_label") == "risk_off" or market_is_risk_off(
        breadth, market_return, market_gap
    ):
        return {
            **common,
            "key": "observe",
            "label": "风险关闭 / 空仓",
            "confidence": round(min(1.0, abs(regime)), 3),
            "candidate_strategies": [],
            "candidate_strategy_keys": [],
            "reasons": [
                f"市场宽度{breadth * 100:.1f}%",
                f"等权涨跌{market_return * 100:+.2f}%",
                "风险阈值已触发",
            ],
        }

    if regime >= 0.35 and breadth >= 0.58 and market_return >= 0.003:
        reasons = [
            f"市场宽度{breadth * 100:.1f}%",
            f"等权涨跌{market_return * 100:+.2f}%",
            "强势扩散支持动量观察",
        ]
        if sentiment_score >= 9:
            reasons.append("情绪过热，追高候选需降权并保留空仓")
        return {
            **common,
            "key": "chase",
            "label": "V4强势延续",
            "confidence": round(min(1.0, 0.45 + max(0.0, regime - 0.35)), 3),
            "candidate_strategies": ["V4强势延续"],
            "candidate_strategy_keys": ["momentum"],
            "reasons": reasons,
        }

    if breadth <= 0.56 and market_return <= 0.004:
        return {
            **common,
            "key": "pullback",
            "label": "V4回撤修复",
            "confidence": round(min(1.0, 0.45 + abs(0.5 - breadth)), 3),
            "candidate_strategies": ["V4回撤修复"],
            "candidate_strategy_keys": ["pullback"],
            "reasons": [
                f"市场宽度{breadth * 100:.1f}%",
                f"等权涨跌{market_return * 100:+.2f}%",
                "市场未形成普涨，优先验证缩量与支撑",
            ],
        }

    return {
        **common,
        "key": "balanced",
        "label": "V4双因子精选",
        "confidence": round(min(1.0, 0.4 + abs(regime) * 0.3), 3),
        "candidate_strategies": ["V4强势延续", "V4回撤修复"],
        "candidate_strategy_keys": ["momentum", "pullback"],
        "reasons": [
            f"市场宽度{breadth * 100:.1f}%",
            f"等权涨跌{market_return * 100:+.2f}%",
            "单一风格优势不足，保留双池但只看Top1",
        ],
    }
