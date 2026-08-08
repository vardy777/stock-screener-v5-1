"""Versioned point-in-time market-data contracts.

These entities are deliberately independent from pandas.  They form the
validated boundary between quote providers and V4 decision/execution code.
Naive timestamps are rejected: silently assigning a timezone would turn an
unknown provider timestamp into false strict evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite
from typing import Any, Iterable, Mapping

from .execution import CHINA_TZ


QUOTE_SCHEMA_VERSION = "quote-v1"
SNAPSHOT_SCHEMA_VERSION = "market-snapshot-v1"
QUALITY_SCHEMA_VERSION = "snapshot-quality-v1"


class ContractViolation(ValueError):
    """Raised when input cannot truthfully satisfy a versioned contract."""


class EvidenceCohort(str, Enum):
    STRICT = "strict"
    PAPER_ONLY = "paper_only"


class QualityReason(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    DUPLICATE_CODE = "duplicate_code"
    INCOMPLETE_COVERAGE = "incomplete_coverage"
    BATCH_DELAY = "batch_delay"
    PROVIDER_CLOCK_SKEW = "provider_clock_skew"
    CROSS_TRADE_DATE = "cross_trade_date"
    MISSING_ORDER_BOOK = "missing_order_book"
    HALTED = "halted"
    LIMIT_LOCKED = "limit_locked"


def _aware_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ContractViolation(f"{field}: invalid datetime") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractViolation(f"{field}: timezone is required")
    return value.astimezone(CHINA_TZ)


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ContractViolation(f"{field}: boolean is not numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"{field}: invalid number") from exc
    if not isfinite(result) or (positive and result <= 0):
        raise ContractViolation(f"{field}: out of range")
    return result


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ContractViolation(f"{field}: boolean is not integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"{field}: invalid integer") from exc
    if result < 0 or float(value) != result:
        raise ContractViolation(f"{field}: out of range")
    return result


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ContractViolation(f"{field}: boolean is required")
    return value


@dataclass(frozen=True)
class QuoteV1:
    code: str
    name: str
    trade_date: str
    exchange_time: str
    provider_time: str
    received_at: str
    last_price: float
    previous_close: float
    bid1: float
    bid1_volume: int
    ask1: float
    ask1_volume: int
    volume: int
    amount: float
    halted: bool
    limit_up: bool
    limit_down: bool
    provider: str
    schema_version: str = QUOTE_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "QuoteV1":
        required = {
            "code", "name", "trade_date", "exchange_time", "provider_time",
            "received_at", "last_price", "previous_close", "bid1",
            "bid1_volume", "ask1", "ask1_volume", "volume", "amount",
            "halted", "limit_up", "limit_down", "provider",
        }
        missing = sorted(required - set(row))
        if missing:
            raise ContractViolation(f"missing fields: {', '.join(missing)}")
        code = str(row["code"])
        if len(code) != 6 or not code.isdigit():
            raise ContractViolation("code: six digits required")
        name = str(row["name"]).strip()
        provider = str(row["provider"]).strip()
        if not name or not provider:
            raise ContractViolation("name/provider: non-empty value required")
        try:
            declared_date = date.fromisoformat(str(row["trade_date"]))
        except ValueError as exc:
            raise ContractViolation("trade_date: ISO date required") from exc
        exchange = _aware_datetime(row["exchange_time"], "exchange_time")
        provider_time = _aware_datetime(row["provider_time"], "provider_time")
        received = _aware_datetime(row["received_at"], "received_at")
        if exchange.date() != declared_date:
            raise ContractViolation("exchange_time: cross trade date")
        if provider_time < exchange:
            raise ContractViolation("provider_time: earlier than exchange_time")
        if received < provider_time:
            raise ContractViolation("received_at: earlier than provider_time")
        return cls(
            code=code,
            name=name,
            trade_date=declared_date.isoformat(),
            exchange_time=exchange.isoformat(),
            provider_time=provider_time.isoformat(),
            received_at=received.isoformat(),
            last_price=_number(row["last_price"], "last_price", positive=True),
            previous_close=_number(row["previous_close"], "previous_close", positive=True),
            bid1=_number(row["bid1"], "bid1"),
            bid1_volume=_integer(row["bid1_volume"], "bid1_volume"),
            ask1=_number(row["ask1"], "ask1"),
            ask1_volume=_integer(row["ask1_volume"], "ask1_volume"),
            volume=_integer(row["volume"], "volume"),
            amount=_number(row["amount"], "amount"),
            halted=_boolean(row["halted"], "halted"),
            limit_up=_boolean(row["limit_up"], "limit_up"),
            limit_down=_boolean(row["limit_down"], "limit_down"),
            provider=provider,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_provider_row(cls, row: Mapping[str, Any]) -> "QuoteV1":
        """Adapt the canonical V4 provider-frame names without guessing time."""

        return cls.from_mapping({
            "code": row.get("code"),
            "name": row.get("name"),
            "trade_date": row.get("trade_date"),
            "exchange_time": row.get("exchange_time"),
            "provider_time": row.get("provider_time"),
            "received_at": row.get("received_at"),
            "last_price": row.get("price"),
            "previous_close": row.get("prev_close"),
            "bid1": row.get("bid1"),
            "bid1_volume": row.get("bid1_volume"),
            "ask1": row.get("ask1"),
            "ask1_volume": row.get("ask1_volume"),
            "volume": row.get("volume"),
            "amount": row.get("amount"),
            "halted": row.get("halted"),
            "limit_up": row.get("limit_up"),
            "limit_down": row.get("limit_down"),
            "provider": row.get("provider"),
        })


@dataclass(frozen=True)
class SnapshotQualityV1:
    cohort: str
    accepted: bool
    reasons: tuple[str, ...]
    expected_codes: int
    valid_codes: int
    coverage: float
    maximum_quote_age_seconds: float
    batch_duration_seconds: float
    schema_version: str = QUALITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


@dataclass(frozen=True)
class MarketSnapshotV1:
    trade_date: str
    session: str
    batch_started_at: str
    batch_completed_at: str
    quotes: tuple[QuoteV1, ...]
    quality: SnapshotQualityV1
    schema_version: str = SNAPSHOT_SCHEMA_VERSION

    @classmethod
    def build(
        cls,
        *,
        trade_date: str,
        session: str,
        batch_started_at: Any,
        batch_completed_at: Any,
        quotes: Iterable[QuoteV1],
        expected_codes: int,
        cohort: EvidenceCohort = EvidenceCohort.STRICT,
        minimum_coverage: float = 0.95,
        maximum_age_seconds: float = 30.0,
        maximum_batch_seconds: float = 30.0,
        require_order_book: bool = True,
    ) -> "MarketSnapshotV1":
        try:
            declared_date = date.fromisoformat(str(trade_date))
        except ValueError as exc:
            raise ContractViolation("trade_date: ISO date required") from exc
        if session not in {"signal", "buy", "sell"}:
            raise ContractViolation("session: unsupported value")
        started = _aware_datetime(batch_started_at, "batch_started_at")
        completed = _aware_datetime(batch_completed_at, "batch_completed_at")
        if completed < started:
            raise ContractViolation("batch_completed_at: earlier than batch_started_at")
        items = tuple(quotes)
        if not all(isinstance(item, QuoteV1) for item in items):
            raise ContractViolation("quotes: QuoteV1 values required")
        expected = _integer(expected_codes, "expected_codes")
        if not 0 <= minimum_coverage <= 1:
            raise ContractViolation("minimum_coverage: must be within 0..1")

        reasons: list[str] = []
        codes = [item.code for item in items]
        if not items:
            reasons.append(QualityReason.EMPTY.value)
        if len(codes) != len(set(codes)):
            reasons.append(QualityReason.DUPLICATE_CODE.value)
        if any(date.fromisoformat(item.trade_date) != declared_date for item in items):
            reasons.append(QualityReason.CROSS_TRADE_DATE.value)
        coverage = len(set(codes)) / expected if expected else 0.0
        if coverage < minimum_coverage:
            reasons.append(QualityReason.INCOMPLETE_COVERAGE.value)
        duration = (completed - started).total_seconds()
        if duration > maximum_batch_seconds:
            reasons.append(QualityReason.BATCH_DELAY.value)
        ages = [
            (completed - datetime.fromisoformat(item.exchange_time)).total_seconds()
            for item in items
        ]
        maximum_age = max(ages, default=0.0)
        if any(age < 0 for age in ages):
            reasons.append(QualityReason.PROVIDER_CLOCK_SKEW.value)
        elif maximum_age > maximum_age_seconds:
            reasons.append(QualityReason.PROVIDER_CLOCK_SKEW.value)
        if require_order_book and any(
            item.bid1 <= 0 or item.ask1 <= 0
            or item.bid1_volume <= 0 or item.ask1_volume <= 0
            for item in items
        ):
            reasons.append(QualityReason.MISSING_ORDER_BOOK.value)
        if any(item.halted for item in items):
            reasons.append(QualityReason.HALTED.value)
        if any(item.limit_up or item.limit_down for item in items):
            reasons.append(QualityReason.LIMIT_LOCKED.value)

        # paper_only may tolerate incomplete full-market coverage and batch
        # latency, but never non-causal/cross-date/invalid execution quotes.
        tolerated = {
            QualityReason.INCOMPLETE_COVERAGE.value,
            QualityReason.BATCH_DELAY.value,
        } if cohort == EvidenceCohort.PAPER_ONLY else set()
        accepted = not any(reason not in tolerated for reason in reasons)
        quality = SnapshotQualityV1(
            cohort=cohort.value,
            accepted=accepted,
            reasons=tuple(reasons or [QualityReason.OK.value]),
            expected_codes=expected,
            valid_codes=len(set(codes)),
            coverage=float(coverage),
            maximum_quote_age_seconds=float(maximum_age),
            batch_duration_seconds=float(duration),
        )
        return cls(
            trade_date=declared_date.isoformat(),
            session=session,
            batch_started_at=started.isoformat(),
            batch_completed_at=completed.isoformat(),
            quotes=items,
            quality=quality,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trade_date": self.trade_date,
            "session": self.session,
            "batch_started_at": self.batch_started_at,
            "batch_completed_at": self.batch_completed_at,
            "quotes": [quote.to_dict() for quote in self.quotes],
            "quality": self.quality.to_dict(),
        }
