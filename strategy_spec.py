"""Shared strategy specification and realistic A-share transaction costs.

This module deliberately has no third-party dependencies so the V4 paper
engine and the research pipeline use exactly the same cash-flow rules.
Rates are expressed as decimal fractions: 0.00025 means 0.025%.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import floor
from typing import Dict, Optional


@dataclass(frozen=True)
class FeeSchedule:
    """Baseline retail A-share fee assumptions used for research."""

    commission_rate: float = 0.00025
    minimum_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001


@dataclass(frozen=True)
class StrategySpec:
    """Frozen v1.0 operating assumptions for the overnight strategy."""

    initial_capital: float = 100_000.0
    max_positions: int = 3
    max_position_fraction: float = 1.0 / 3.0
    lot_size: int = 100
    signal_cutoff: str = "14:49:59"
    buy_start: str = "14:50:00"
    buy_end: str = "14:51:59"
    sell_start: str = "09:30:00"
    target_net_return: float = 0.01
    large_loss_threshold: float = -0.02
    minimum_stock_price: float = 5.0
    maximum_stock_price: float = 200.0
    buy_slippage_rate: float = 0.0005
    sell_slippage_rate: float = 0.0005
    stress_slippage_rate: float = 0.001
    fees: FeeSchedule = FeeSchedule()

    def position_budget(self, total_equity: float) -> float:
        """Maximum all-in cash allocated to one stock."""

        return max(0.0, float(total_equity) * self.max_position_fraction)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


DEFAULT_SPEC = StrategySpec()


class TradeCostModel:
    """Convert reference prices into executable cash flows.

    Reference prices come from market data. Slippage converts a reference
    price into a simulated fill. Fees are then charged on the fill notional.
    """

    def __init__(self, spec: StrategySpec = DEFAULT_SPEC):
        self.spec = spec

    def commission(self, notional: float) -> float:
        if notional <= 0:
            return 0.0
        return max(
            float(notional) * self.spec.fees.commission_rate,
            self.spec.fees.minimum_commission,
        )

    def buy_fill_price(
        self, reference_price: float, slippage_rate: Optional[float] = None
    ) -> float:
        rate = self.spec.buy_slippage_rate if slippage_rate is None else slippage_rate
        return float(reference_price) * (1.0 + float(rate))

    def sell_fill_price(
        self, reference_price: float, slippage_rate: Optional[float] = None
    ) -> float:
        rate = self.spec.sell_slippage_rate if slippage_rate is None else slippage_rate
        return float(reference_price) * (1.0 - float(rate))

    def buy_fees(self, notional: float) -> Dict[str, float]:
        commission = self.commission(notional)
        transfer_fee = max(0.0, float(notional)) * self.spec.fees.transfer_fee_rate
        return {
            "commission": commission,
            "transfer_fee": transfer_fee,
            "stamp_duty": 0.0,
            "total": commission + transfer_fee,
        }

    def sell_fees(self, notional: float) -> Dict[str, float]:
        commission = self.commission(notional)
        transfer_fee = max(0.0, float(notional)) * self.spec.fees.transfer_fee_rate
        stamp_duty = max(0.0, float(notional)) * self.spec.fees.stamp_duty_rate
        return {
            "commission": commission,
            "transfer_fee": transfer_fee,
            "stamp_duty": stamp_duty,
            "total": commission + transfer_fee + stamp_duty,
        }

    def buy_cash_required(self, fill_price: float, shares: int) -> Dict[str, float]:
        notional = float(fill_price) * int(shares)
        fees = self.buy_fees(notional)
        return {
            "fill_price": float(fill_price),
            "notional": notional,
            **fees,
            "cash_out": notional + fees["total"],
        }

    def sell_cash_received(self, fill_price: float, shares: int) -> Dict[str, float]:
        notional = float(fill_price) * int(shares)
        fees = self.sell_fees(notional)
        return {
            "fill_price": float(fill_price),
            "notional": notional,
            **fees,
            "cash_in": notional - fees["total"],
        }

    def max_affordable_shares(
        self,
        reference_price: float,
        cash_budget: float,
        *,
        apply_buy_slippage: bool = True,
    ) -> int:
        """Largest board-lot position whose all-in cost fits the budget."""

        if reference_price <= 0 or cash_budget <= 0:
            return 0
        fill = (
            self.buy_fill_price(reference_price)
            if apply_buy_slippage
            else float(reference_price)
        )
        lots = floor(float(cash_budget) / (fill * self.spec.lot_size))
        shares = max(0, lots * self.spec.lot_size)
        while shares > 0:
            required = self.buy_cash_required(fill, shares)["cash_out"]
            if required <= float(cash_budget) + 1e-9:
                return shares
            shares -= self.spec.lot_size
        return 0

    def round_trip(
        self,
        buy_reference: float,
        sell_reference: float,
        shares: int,
        *,
        apply_slippage: bool = True,
        buy_slippage_rate: Optional[float] = None,
        sell_slippage_rate: Optional[float] = None,
    ) -> Dict[str, float]:
        if shares <= 0:
            raise ValueError("shares must be positive")
        if buy_reference <= 0 or sell_reference <= 0:
            raise ValueError("reference prices must be positive")

        if apply_slippage:
            buy_fill = self.buy_fill_price(buy_reference, buy_slippage_rate)
            sell_fill = self.sell_fill_price(sell_reference, sell_slippage_rate)
        else:
            buy_fill = float(buy_reference)
            sell_fill = float(sell_reference)

        buy = self.buy_cash_required(buy_fill, shares)
        sell = self.sell_cash_received(sell_fill, shares)
        pnl = sell["cash_in"] - buy["cash_out"]
        net_return = pnl / buy["cash_out"] if buy["cash_out"] else 0.0
        gross_return = sell_fill / buy_fill - 1.0
        return {
            "shares": int(shares),
            "buy_reference": float(buy_reference),
            "sell_reference": float(sell_reference),
            "buy_fill": buy_fill,
            "sell_fill": sell_fill,
            "buy_notional": buy["notional"],
            "sell_notional": sell["notional"],
            "buy_commission": buy["commission"],
            "sell_commission": sell["commission"],
            "buy_transfer_fee": buy["transfer_fee"],
            "sell_transfer_fee": sell["transfer_fee"],
            "stamp_duty": sell["stamp_duty"],
            "total_fees": buy["total"] + sell["total"],
            "cash_out": buy["cash_out"],
            "cash_in": sell["cash_in"],
            "pnl": pnl,
            "gross_return": gross_return,
            "net_return": net_return,
            "target_1pct": int(net_return >= self.spec.target_net_return),
            "large_loss": int(net_return <= self.spec.large_loss_threshold),
        }

    def required_sell_reference(
        self,
        buy_reference: float,
        shares: int,
        target_net_return: Optional[float] = None,
    ) -> float:
        """Solve the pre-slippage sell reference required for a net target."""

        target = (
            self.spec.target_net_return
            if target_net_return is None
            else float(target_net_return)
        )
        buy_fill = self.buy_fill_price(buy_reference)
        buy = self.buy_cash_required(buy_fill, shares)
        required_cash_in = buy["cash_out"] * (1.0 + target)

        low = float(buy_reference)
        high = float(buy_reference) * 2.0
        for _ in range(80):
            mid = (low + high) / 2.0
            sell_fill = self.sell_fill_price(mid)
            cash_in = self.sell_cash_received(sell_fill, shares)["cash_in"]
            if cash_in >= required_cash_in:
                high = mid
            else:
                low = mid
        return high
