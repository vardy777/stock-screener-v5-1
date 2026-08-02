"""Shared market-regime functions used by research and live decisions."""

from __future__ import annotations


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
