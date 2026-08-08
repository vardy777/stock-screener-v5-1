"""Immutable offline-only P3 paper execution contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json
from math import isfinite
from typing import Any, Mapping


ORDER_VERSION = "paper-order-intent-v1"
FILL_VERSION = "paper-fill-v1"
ROUND_TRIP_VERSION = "paper-round-trip-v1"


class PaperContractViolation(ValueError):
    pass


def _timestamp(value: Any, field: str) -> str:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise PaperContractViolation(f"{field}: invalid datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperContractViolation(f"{field}: timezone is required")
    return parsed.isoformat(timespec="seconds")


def _day(value: Any, field: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise PaperContractViolation(f"{field}: ISO date required") from exc


def _positive(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PaperContractViolation(f"{field}: numeric value required") from exc
    if not isfinite(result) or result <= 0:
        raise PaperContractViolation(f"{field}: positive value required")
    return result


def _identity(prefix: str, payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class PaperOrderIntentV1:
    intent_id: str
    decision_id: str
    side: str
    code: str
    name: str
    trade_date: str
    created_at: str
    reference_price: float
    shares: int
    cash_budget: float
    market_snapshot_id: str
    eligible_sell_date: str
    schema_version: str = ORDER_VERSION

    @classmethod
    def build(cls, **value) -> "PaperOrderIntentV1":
        side = str(value.get("side", "")).upper()
        if side not in {"BUY", "SELL"}:
            raise PaperContractViolation("side: BUY or SELL required")
        code = str(value.get("code", ""))
        if len(code) != 6 or not code.isdigit():
            raise PaperContractViolation("code: six digits required")
        shares = int(value.get("shares", 0))
        if shares <= 0 or shares % 100:
            raise PaperContractViolation("shares: positive board lots required")
        decision_id = str(value.get("decision_id", ""))
        snapshot_id = str(value.get("market_snapshot_id", ""))
        if not decision_id.startswith("cd-"):
            raise PaperContractViolation("decision_id: final confirmation required")
        if not snapshot_id.startswith("ms1-"):
            raise PaperContractViolation("market_snapshot_id: required")
        trade_date = _day(value.get("trade_date"), "trade_date")
        eligible = _day(value.get("eligible_sell_date"), "eligible_sell_date")
        if side == "BUY" and eligible <= trade_date:
            raise PaperContractViolation("eligible_sell_date: must follow buy date")
        if side == "SELL" and trade_date < eligible:
            raise PaperContractViolation("trade_date: sell before T+1 eligibility")
        created_at = _timestamp(value.get("created_at"), "created_at")
        if datetime.fromisoformat(created_at).date().isoformat() != trade_date:
            raise PaperContractViolation("created_at: trade date mismatch")
        payload = {
            "schema_version": ORDER_VERSION, "decision_id": decision_id,
            "side": side, "code": code, "name": str(value.get("name", "")),
            "trade_date": trade_date,
            "created_at": created_at,
            "reference_price": _positive(value.get("reference_price"), "reference_price"),
            "shares": shares, "cash_budget": _positive(value.get("cash_budget"), "cash_budget"),
            "market_snapshot_id": snapshot_id, "eligible_sell_date": eligible,
        }
        return cls(intent_id=_identity("poi", payload), **{k: v for k, v in payload.items() if k != "schema_version"})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def verify(self) -> "PaperOrderIntentV1":
        if self.schema_version != ORDER_VERSION:
            raise PaperContractViolation("intent: schema mismatch")
        payload = self.to_dict()
        payload.pop("intent_id")
        if self.intent_id != _identity("poi", payload):
            raise PaperContractViolation("intent: content hash mismatch")
        return self

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PaperOrderIntentV1":
        try:
            return cls(**dict(value)).verify()
        except TypeError as exc:
            raise PaperContractViolation("intent: invalid fields") from exc


@dataclass(frozen=True)
class PaperFillV1:
    fill_id: str
    intent_id: str
    decision_id: str
    side: str
    code: str
    name: str
    trade_date: str
    filled_at: str
    fill_price: float
    shares: int
    notional: float
    commission: float
    transfer_fee: float
    stamp_duty: float
    total_fees: float
    cash_flow: float
    market_snapshot_id: str
    eligible_sell_date: str
    schema_version: str = FILL_VERSION

    @classmethod
    def build(cls, intent: PaperOrderIntentV1, *, filled_at, fill_price, costs) -> "PaperFillV1":
        if not isinstance(intent, PaperOrderIntentV1):
            raise PaperContractViolation("intent: PaperOrderIntentV1 required")
        intent.verify()
        price = _positive(fill_price, "fill_price")
        fees = {name: float(costs.get(name, 0.0)) for name in (
            "notional", "commission", "transfer_fee", "stamp_duty", "total"
        )}
        if any(not isfinite(item) or item < 0 for item in fees.values()):
            raise PaperContractViolation("costs: finite non-negative values required")
        expected_notional = price * intent.shares
        if abs(fees["notional"] - expected_notional) > 0.01:
            raise PaperContractViolation("costs: notional mismatch")
        cash_flow = -expected_notional - fees["total"] if intent.side == "BUY" else expected_notional - fees["total"]
        if intent.side == "BUY" and -cash_flow > intent.cash_budget + 0.01:
            raise PaperContractViolation("fill: frozen cash budget exceeded")
        fill_time = _timestamp(filled_at, "filled_at")
        if datetime.fromisoformat(fill_time).date().isoformat() != intent.trade_date:
            raise PaperContractViolation("filled_at: trade date mismatch")
        payload = {
            "schema_version": FILL_VERSION, "intent_id": intent.intent_id,
            "decision_id": intent.decision_id, "side": intent.side,
            "code": intent.code, "name": intent.name, "trade_date": intent.trade_date,
            "filled_at": fill_time, "fill_price": price,
            "shares": intent.shares, "notional": expected_notional,
            "commission": fees["commission"], "transfer_fee": fees["transfer_fee"],
            "stamp_duty": fees["stamp_duty"], "total_fees": fees["total"],
            "cash_flow": cash_flow, "market_snapshot_id": intent.market_snapshot_id,
            "eligible_sell_date": intent.eligible_sell_date,
        }
        return cls(fill_id=_identity("pf", payload), **{k: v for k, v in payload.items() if k != "schema_version"})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def verify(self) -> "PaperFillV1":
        if self.schema_version != FILL_VERSION:
            raise PaperContractViolation("fill: schema mismatch")
        payload = self.to_dict()
        payload.pop("fill_id")
        expected = _identity("pf", payload)
        if self.fill_id != expected:
            raise PaperContractViolation("fill: content hash mismatch")
        return self

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PaperFillV1":
        try:
            return cls(**dict(value)).verify()
        except TypeError as exc:
            raise PaperContractViolation("fill: invalid fields") from exc


@dataclass(frozen=True)
class PaperRoundTripV1:
    round_trip_id: str
    code: str
    shares: int
    buy_fill_id: str
    sell_fill_id: str
    cash_out: float
    cash_in: float
    net_pnl: float
    net_return: float
    total_fees: float
    schema_version: str = ROUND_TRIP_VERSION

    @classmethod
    def build(cls, buy: PaperFillV1, sell: PaperFillV1) -> "PaperRoundTripV1":
        if buy.side != "BUY" or sell.side != "SELL":
            raise PaperContractViolation("round trip: BUY then SELL required")
        if buy.code != sell.code or buy.shares != sell.shares:
            raise PaperContractViolation("round trip: code/shares mismatch")
        if sell.trade_date < buy.eligible_sell_date:
            raise PaperContractViolation("round trip: T+1 violation")
        cash_out, cash_in = -buy.cash_flow, sell.cash_flow
        payload = {
            "schema_version": ROUND_TRIP_VERSION, "code": buy.code,
            "shares": buy.shares, "buy_fill_id": buy.fill_id,
            "sell_fill_id": sell.fill_id, "cash_out": cash_out,
            "cash_in": cash_in, "net_pnl": cash_in - cash_out,
            "net_return": (cash_in - cash_out) / cash_out,
            "total_fees": buy.total_fees + sell.total_fees,
        }
        return cls(round_trip_id=_identity("prt", payload), **{k: v for k, v in payload.items() if k != "schema_version"})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
