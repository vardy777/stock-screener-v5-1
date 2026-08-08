"""Immutable P2 entities shared by selection, push, execution and dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
import hashlib
import json
from typing import Any, Iterable, Mapping
from types import MappingProxyType

from .execution import CHINA_TZ


MORNING_POOL_VERSION = "morning-pool-v1"
CONFIRMATION_VERSION = "confirmation-decision-v1"


class DecisionContractViolation(ValueError):
    pass


class DecisionOutcome(str, Enum):
    BUY = "BUY"
    EMPTY = "EMPTY"
    BLOCKED = "BLOCKED"


class DecisionReason(str, Enum):
    ELIGIBLE_TOP1 = "eligible_top1"
    NO_CANDIDATE = "no_candidate"
    MISSING_MORNING_POOL = "missing_morning_pool"
    OUTSIDE_MORNING_POOL = "outside_morning_pool"
    RESEARCH_LOCKED = "research_locked"
    MODEL_UNPUBLISHED = "model_unpublished"
    OUTSIDE_BUY_WINDOW = "outside_buy_window"
    MARKET_RISK = "market_risk"
    DATA_INVALID = "data_invalid"
    NOT_TOP1 = "not_top1"
    SCORE_POLICY = "score_policy"
    SOURCE_INVALID = "source_invalid"
    QUOTE_INVALID = "quote_invalid"
    UNKNOWN_BLOCK = "unknown_block"


def _timestamp(value: Any, field: str) -> str:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise DecisionContractViolation(f"{field}: invalid datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DecisionContractViolation(f"{field}: timezone is required")
    return parsed.astimezone(CHINA_TZ).isoformat(timespec="seconds")


def _trade_date(value: Any) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise DecisionContractViolation("trade_date: ISO date required") from exc


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _identity(prefix: str, value: Mapping[str, Any]) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:24]


def _candidate_rows(candidates: Iterable[Mapping[str, Any]]) -> tuple[dict, ...]:
    rows = tuple(dict(item) for item in candidates)
    codes = [str(item.get("code", "")).zfill(6) for item in rows]
    if any(not code.isdigit() or len(code) != 6 for code in codes):
        raise DecisionContractViolation("candidate code: six digits required")
    if len(codes) != len(set(codes)):
        raise DecisionContractViolation("candidate code: duplicate")
    if any(item.get("v4_candidate_origin") != "V4" for item in rows):
        raise DecisionContractViolation("candidate origin: V4 required")
    for item, code in zip(rows, codes):
        item["code"] = code
    return rows


_REASON_TEXT = (
    ("研究准入", DecisionReason.RESEARCH_LOCKED),
    ("生产模型", DecisionReason.MODEL_UNPUBLISHED),
    ("执行窗口", DecisionReason.OUTSIDE_BUY_WINDOW),
    ("周末休市", DecisionReason.OUTSIDE_BUY_WINDOW),
    ("交易所公告休市", DecisionReason.OUTSIDE_BUY_WINDOW),
    ("市场风险", DecisionReason.MARKET_RISK),
    ("数据质量", DecisionReason.DATA_INVALID),
    ("状态数据无效", DecisionReason.DATA_INVALID),
    ("Top1", DecisionReason.NOT_TOP1),
    ("规则分", DecisionReason.SCORE_POLICY),
    ("评分血缘", DecisionReason.SCORE_POLICY),
    ("候选来源", DecisionReason.SOURCE_INVALID),
    ("模拟候选", DecisionReason.SOURCE_INVALID),
    ("价格", DecisionReason.QUOTE_INVALID),
    ("时效", DecisionReason.QUOTE_INVALID),
    ("行情时间戳", DecisionReason.QUOTE_INVALID),
    ("母池链路", DecisionReason.OUTSIDE_MORNING_POOL),
)


def reason_codes(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    texts = list(candidate.get("v4_paper_block_reasons", []))
    codes = []
    for text in texts:
        matched = next((code for token, code in _REASON_TEXT if token in str(text)), None)
        value = (matched or DecisionReason.UNKNOWN_BLOCK).value
        if value not in codes:
            codes.append(value)
    return tuple(codes)


@dataclass(frozen=True)
class MorningPoolV1:
    pool_id: str
    trade_date: str
    captured_at: str
    candidate_codes: tuple[str, ...]
    candidates: tuple[dict, ...]
    market_state: dict
    schema_version: str = MORNING_POOL_VERSION

    def __post_init__(self):
        object.__setattr__(self, "candidate_codes", tuple(self.candidate_codes))
        object.__setattr__(self, "candidates", _freeze(self.candidates))
        object.__setattr__(self, "market_state", _freeze(self.market_state))

    @classmethod
    def build(cls, trade_date: str, captured_at: Any, candidates, market_state) -> "MorningPoolV1":
        day = _trade_date(trade_date)
        timestamp = _timestamp(captured_at, "captured_at")
        rows = _candidate_rows(candidates)
        identity_payload = {
            "schema_version": MORNING_POOL_VERSION,
            "trade_date": day,
            "candidates": rows,
            "market_state": dict(market_state),
        }
        return cls(
            pool_id=_identity("mp", identity_payload), trade_date=day,
            captured_at=timestamp,
            candidate_codes=tuple(item["code"] for item in rows),
            candidates=rows, market_state=dict(market_state),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "pool_id": self.pool_id,
            "trade_date": self.trade_date, "captured_at": self.captured_at,
            "candidate_codes": list(self.candidate_codes),
            "candidates": _thaw(self.candidates),
            "market_state": _thaw(self.market_state),
        }


@dataclass(frozen=True)
class ConfirmationDecisionV1:
    decision_id: str
    morning_pool_id: str
    trade_date: str
    decided_at: str
    outcome: str
    reason_codes: tuple[str, ...]
    candidate_codes: tuple[str, ...]
    candidates: tuple[dict, ...]
    market_state: dict
    schema_version: str = CONFIRMATION_VERSION

    def __post_init__(self):
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "candidate_codes", tuple(self.candidate_codes))
        object.__setattr__(self, "candidates", _freeze(self.candidates))
        object.__setattr__(self, "market_state", _freeze(self.market_state))

    @classmethod
    def build(cls, morning: MorningPoolV1, decided_at: Any, candidates, market_state):
        rows = _candidate_rows(candidates)
        outside = [item["code"] for item in rows if item["code"] not in morning.candidate_codes]
        if outside:
            raise DecisionContractViolation(
                f"confirmation outside morning pool: {','.join(outside)}"
            )
        eligible = [item for item in rows if item.get("v4_paper_eligible") is True]
        if eligible:
            outcome = DecisionOutcome.BUY
            reasons = (DecisionReason.ELIGIBLE_TOP1.value,)
        elif rows:
            outcome = DecisionOutcome.BLOCKED
            reasons = tuple(dict.fromkeys(
                reason for item in rows for reason in reason_codes(item)
            )) or (DecisionReason.UNKNOWN_BLOCK.value,)
        else:
            outcome = DecisionOutcome.EMPTY
            reasons = (DecisionReason.NO_CANDIDATE.value,)
        identity_payload = {
            "schema_version": CONFIRMATION_VERSION,
            "morning_pool_id": morning.pool_id,
            "trade_date": morning.trade_date,
            "outcome": outcome.value,
            "reason_codes": reasons,
            "candidates": rows,
            "market_state": dict(market_state),
        }
        return cls(
            decision_id=_identity("cd", identity_payload),
            morning_pool_id=morning.pool_id, trade_date=morning.trade_date,
            decided_at=_timestamp(decided_at, "decided_at"), outcome=outcome.value,
            reason_codes=reasons,
            candidate_codes=tuple(item["code"] for item in rows),
            candidates=rows, market_state=dict(market_state),
        )

    @classmethod
    def blocked_without_morning(
        cls, trade_date: str, decided_at: Any, market_state: Mapping[str, Any]
    ) -> "ConfirmationDecisionV1":
        day = _trade_date(trade_date)
        reasons = (DecisionReason.MISSING_MORNING_POOL.value,)
        identity_payload = {
            "schema_version": CONFIRMATION_VERSION,
            "morning_pool_id": "missing",
            "trade_date": day,
            "outcome": DecisionOutcome.BLOCKED.value,
            "reason_codes": reasons,
            "candidates": [],
            "market_state": dict(market_state),
        }
        return cls(
            decision_id=_identity("cd", identity_payload),
            morning_pool_id="missing", trade_date=day,
            decided_at=_timestamp(decided_at, "decided_at"),
            outcome=DecisionOutcome.BLOCKED.value, reason_codes=reasons,
            candidate_codes=(), candidates=(), market_state=dict(market_state),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "morning_pool_id": self.morning_pool_id,
            "trade_date": self.trade_date, "decided_at": self.decided_at,
            "outcome": self.outcome, "reason_codes": list(self.reason_codes),
            "candidate_codes": list(self.candidate_codes),
            "candidates": _thaw(self.candidates),
            "market_state": _thaw(self.market_state),
        }
