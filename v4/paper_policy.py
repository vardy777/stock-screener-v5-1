"""Predeclared causal admission policy for unbiased paper observations."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from .execution import TradingClock


PAPER_POLICY_VERSION = "paper-top1-integrity-v1"
MAX_RET_5D_PCT = 30.0
MAX_DISTANCE_MA10_PCT = 25.0
MIN_INTRADAY_AMOUNT_YI = 1.0


@dataclass(frozen=True)
class PaperPolicyResult:
    eligible: bool
    reasons: tuple[str, ...]
    policy_version: str = PAPER_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "policy_version": self.policy_version,
        }


def evaluate_paper_candidate(
    candidate: Mapping[str, Any],
    market_state: Mapping[str, Any],
    *,
    buy_status=None,
    reference_time=None,
) -> PaperPolicyResult:
    """Admit causal Top1 observations without an outcome-fitted score cutoff."""

    item = candidate or {}
    market = market_state or {}
    status = buy_status or TradingClock.action_status("buy")
    reasons = []
    if item.get("selection_stage") != "confirmation_1450":
        reasons.append("仅允14:50确认候选进入模拟观测")
    if item.get("linkage_status") != "confirmed_from_morning_pool":
        reasons.append("未通过09:25母池链路确认")
    if int(item.get("rank", 0) or 0) != 1:
        reasons.append("模拟观测仅执行Top1")

    score_version = str(item.get("score_version", ""))
    score_values = (
        item.get("base_score"), item.get("confirm_delta"), item.get("decision_score")
    )
    try:
        score_lineage_valid = bool(
            score_version == "v4-base-plus-confirm-delta-v1"
            and all(isfinite(float(value)) for value in score_values)
            and abs(
                float(item["decision_score"])
                - float(item["base_score"])
                - float(item["confirm_delta"])
            ) <= 0.011
        )
    except (TypeError, ValueError):
        score_lineage_valid = False
    if not score_lineage_valid:
        reasons.append("确认评分血缘缺失或不一致")

    coverage = float(
        market.get("fresh_quote_coverage", market.get("quote_coverage", 0.0)) or 0.0
    )
    paper_market_valid = bool(
        item.get("v4_paper_market_valid", market.get("data_valid") is True)
    )
    mode = item.get("v4_paper_market_mode", market.get("mode_label", "neutral"))
    if not paper_market_valid or coverage < 0.95:
        reasons.append("市场数据覆盖或质量未达到95%")
    if mode == "risk_off":
        reasons.append("市场风险关闭")
    if item.get("v4_candidate_origin") != "V4" or item.get("is_mock"):
        reasons.append("候选来源不合格")
    if not status.allowed:
        reasons.append(status.reason)
    if float(item.get("price", 0.0) or 0.0) <= 0 or not TradingClock.quote_is_fresh(
        item.get("quote_time"), now=reference_time
    ):
        reasons.append("确认价格或时效不合格")
    # Legacy frozen fixtures predate explicit order-book fields. Production
    # selectors now always carry them; when present they are fail-closed.
    if ("ask1" in item or "ask1_volume" in item) and (
        float(item.get("ask1", 0.0) or 0.0) <= 0
        or int(item.get("ask1_volume", 0) or 0) <= 0
    ):
        reasons.append("确认卖一盘口不可成交")
    if item.get("halted") is True:
        reasons.append("确认时标的已停牌")
    if item.get("limit_up") is True or item.get("limit_down") is True:
        reasons.append("确认时标的涨跌停锁定")
    # Predeclared safety rails prevent extreme momentum/chase observations
    # from becoming paper fills. They are risk controls, not fitted win-rate
    # thresholds, and must be evaluated later as a frozen policy cohort.
    if float(item.get("near_5d_return", 0.0) or 0.0) > MAX_RET_5D_PCT:
        reasons.append("近5日涨幅过热")
    if float(item.get("dist_to_ma10", 0.0) or 0.0) > MAX_DISTANCE_MA10_PCT:
        reasons.append("价格偏离MA10过大")
    if "amount_yi" in item and float(item.get("amount_yi", 0.0) or 0.0) < MIN_INTRADAY_AMOUNT_YI:
        reasons.append("当日成交额不足")
    return PaperPolicyResult(not reasons, tuple(dict.fromkeys(reasons)))
