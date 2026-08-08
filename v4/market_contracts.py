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
import hashlib
import json
from math import isfinite
from typing import Any, Iterable, Mapping

from .execution import CHINA_TZ


QUOTE_SCHEMA_VERSION = "quote-v1"
SNAPSHOT_SCHEMA_VERSION = "market-snapshot-v1"
QUALITY_SCHEMA_VERSION = "snapshot-quality-v1"
MARKET_STATE_SCHEMA_VERSION = "market-state-v1"


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
    open_price: float
    high_price: float
    low_price: float
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
            open_price=_number(row.get("open_price", row["previous_close"]), "open_price", positive=True),
            high_price=_number(row.get("high_price", row["last_price"]), "high_price", positive=True),
            low_price=_number(row.get("low_price", row["last_price"]), "low_price", positive=True),
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
            "open_price": row.get("open") or row.get("prev_close"),
            "high_price": row.get("high") or row.get("price"),
            "low_price": row.get("low") or row.get("price"),
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

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SnapshotQualityV1":
        if value.get("schema_version") != QUALITY_SCHEMA_VERSION:
            raise ContractViolation("quality: unsupported schema version")
        try:
            return cls(
                cohort=EvidenceCohort(str(value["cohort"])).value,
                accepted=_boolean(value["accepted"], "quality.accepted"),
                reasons=tuple(str(item) for item in value["reasons"]),
                expected_codes=_integer(value["expected_codes"], "quality.expected_codes"),
                valid_codes=_integer(value["valid_codes"], "quality.valid_codes"),
                coverage=_number(value["coverage"], "quality.coverage"),
                maximum_quote_age_seconds=_number(value["maximum_quote_age_seconds"], "quality.maximum_quote_age_seconds"),
                batch_duration_seconds=_number(value["batch_duration_seconds"], "quality.batch_duration_seconds"),
            )
        except KeyError as exc:
            raise ContractViolation(f"quality: missing field {exc.args[0]}") from exc


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
        if session not in {"morning", "signal", "buy", "sell"}:
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
            (session == "buy" and (item.ask1 <= 0 or item.ask1_volume <= 0))
            or (session == "sell" and (item.bid1 <= 0 or item.bid1_volume <= 0))
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
        payload = {
            "schema_version": self.schema_version,
            "trade_date": self.trade_date,
            "session": self.session,
            "batch_started_at": self.batch_started_at,
            "batch_completed_at": self.batch_completed_at,
            "quotes": [quote.to_dict() for quote in self.quotes],
            "quality": self.quality.to_dict(),
        }
        payload["snapshot_id"] = self.snapshot_id
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MarketSnapshotV1":
        if value.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
            raise ContractViolation("snapshot: unsupported schema version")
        try:
            snapshot = cls(
                trade_date=date.fromisoformat(str(value["trade_date"])).isoformat(),
                session=str(value["session"]),
                batch_started_at=_aware_datetime(value["batch_started_at"], "batch_started_at").isoformat(),
                batch_completed_at=_aware_datetime(value["batch_completed_at"], "batch_completed_at").isoformat(),
                quotes=tuple(QuoteV1.from_mapping(item) for item in value["quotes"]),
                quality=SnapshotQualityV1.from_mapping(value["quality"]),
            )
        except KeyError as exc:
            raise ContractViolation(f"snapshot: missing field {exc.args[0]}") from exc
        if snapshot.session not in {"morning", "signal", "buy", "sell"}:
            raise ContractViolation("session: unsupported value")
        codes = {quote.code for quote in snapshot.quotes}
        if snapshot.quality.valid_codes != len(codes):
            raise ContractViolation("quality.valid_codes: snapshot mismatch")
        expected_coverage = (
            len(codes) / snapshot.quality.expected_codes
            if snapshot.quality.expected_codes else 0.0
        )
        if abs(snapshot.quality.coverage - expected_coverage) > 1e-12:
            raise ContractViolation("quality.coverage: snapshot mismatch")
        declared_id = value.get("snapshot_id")
        if declared_id != snapshot.snapshot_id:
            raise ContractViolation("snapshot_id: content hash mismatch")
        return snapshot

    @property
    def snapshot_id(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "trade_date": self.trade_date,
            "session": self.session,
            "batch_started_at": self.batch_started_at,
            "batch_completed_at": self.batch_completed_at,
            "quotes": [quote.to_dict() for quote in self.quotes],
            "quality": self.quality.to_dict(),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "ms1-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MarketStateV1:
    snapshot_id: str
    trade_date: str
    as_of: str
    mode: str
    data_valid: bool
    metrics: Mapping[str, Any]
    analytics_version: str
    schema_version: str = MARKET_STATE_SCHEMA_VERSION

    @classmethod
    def build(
        cls, snapshot: MarketSnapshotV1, *, mode: str, data_valid: bool,
        metrics: Mapping[str, Any], analytics_version: str,
    ) -> "MarketStateV1":
        if not isinstance(snapshot, MarketSnapshotV1):
            raise ContractViolation("snapshot: MarketSnapshotV1 required")
        if mode not in {"risk_off", "neutral", "risk_on", "unavailable"}:
            raise ContractViolation("mode: unsupported value")
        if not isinstance(data_valid, bool):
            raise ContractViolation("data_valid: boolean is required")
        as_of = _aware_datetime(snapshot.batch_completed_at, "as_of")
        return cls(
            snapshot_id=snapshot.snapshot_id,
            trade_date=snapshot.trade_date,
            as_of=as_of.isoformat(),
            mode=mode,
            data_valid=data_valid,
            metrics=dict(metrics),
            analytics_version=str(analytics_version),
        )

    @property
    def market_state_id(self) -> str:
        raw = json.dumps(self.to_dict(include_id=False), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "mstate1-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "trade_date": self.trade_date,
            "as_of": self.as_of,
            "mode": self.mode,
            "data_valid": self.data_valid,
            "metrics": dict(self.metrics),
            "analytics_version": self.analytics_version,
        }
        if include_id:
            payload["market_state_id"] = self.market_state_id
        return payload

    def to_projection(self) -> dict[str, Any]:
        """Compatibility-shaped immutable projection with explicit lineage."""
        payload = dict(self.metrics)
        payload.update({
            "market_state_schema_version": self.schema_version,
            "market_state_id": self.market_state_id,
            "snapshot_id": self.snapshot_id,
            "trade_date": self.trade_date,
            "as_of": self.as_of,
            "mode_label": self.mode,
            "data_valid": self.data_valid,
            "analytics_version": self.analytics_version,
        })
        return payload
