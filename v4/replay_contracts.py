"""Immutable feature inputs required by deterministic P2 replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from types import MappingProxyType

from phase1.overnight.dataset import FEATURE_COLUMNS


FEATURE_CONTEXT_VERSION = "feature-context-v1"
PREVIOUS_CONTEXT_COLUMNS = (
    "code", "context_date", "context_prev_close", "volume_mean_20",
    "ma5_base", "ma10_base", "ma20_base", "ret_1d", "ret_3d", "ret_5d",
    "ret_10d", "ret_20d", "volatility_20", "overnight_mean_20",
    "overnight_hit_1pct_20",
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


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


@dataclass(frozen=True)
class FeatureContextV1:
    trade_date: str
    expected_previous_session: str
    feature_as_of: str
    previous_context: tuple[dict, ...]
    confirmation_features: Mapping[str, Mapping[str, Any]]
    previous_context_id: str
    context_id: str
    input_snapshot_id: str = ""
    schema_version: str = FEATURE_CONTEXT_VERSION

    def __post_init__(self):
        object.__setattr__(self, "previous_context", _freeze(self.previous_context))
        object.__setattr__(self, "confirmation_features", _freeze(self.confirmation_features))

    @classmethod
    def build(
        cls, *, trade_date, expected_previous_session, feature_as_of,
        previous_context, confirmation_features, input_snapshot_id="",
    ) -> "FeatureContextV1":
        day = date.fromisoformat(str(trade_date)).isoformat()
        previous = date.fromisoformat(str(expected_previous_session)).isoformat()
        timestamp = datetime.fromisoformat(str(feature_as_of))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("feature_as_of: timezone is required")
        rows = tuple(
            {name: row[name] for name in PREVIOUS_CONTEXT_COLUMNS}
            for row in previous_context
            if isinstance(row, Mapping)
            and all(name in row for name in PREVIOUS_CONTEXT_COLUMNS)
        )
        if not rows or any(str(row.get("context_date")) != previous for row in rows):
            raise ValueError("previous_context: context date mismatch or empty")
        if any(
            len(str(row.get("code", ""))) != 6
            or not str(row.get("code", "")).isdigit()
            for row in rows
        ):
            raise ValueError("previous_context: six-digit code required")
        raw_feature_codes = [str(code) for code in confirmation_features]
        if any(not code.isdigit() or len(code) != 6 for code in raw_feature_codes):
            raise ValueError("confirmation_features: six-digit code required")
        features = {
            str(code).zfill(6): {name: values[name] for name in FEATURE_COLUMNS}
            for code, values in confirmation_features.items()
            if isinstance(values, Mapping) and all(name in values for name in FEATURE_COLUMNS)
        }
        if not features:
            raise ValueError("confirmation_features: complete rows required")
        payload = {
            "schema_version": FEATURE_CONTEXT_VERSION,
            "trade_date": day,
            "expected_previous_session": previous,
            "feature_as_of": timestamp.isoformat(),
            "previous_context": rows,
            "confirmation_features": features,
        }
        if input_snapshot_id:
            if not str(input_snapshot_id).startswith("ms1-"):
                raise ValueError("input_snapshot_id: MarketSnapshotV1 id required")
            payload["input_snapshot_id"] = str(input_snapshot_id)
        previous_payload = {
            "schema_version": FEATURE_CONTEXT_VERSION,
            "trade_date": day,
            "expected_previous_session": previous,
            "previous_context": rows,
        }
        previous_context_id = "pc1-" + hashlib.sha256(
            _canonical(previous_payload).encode("utf-8")
        ).hexdigest()
        context_id = "fc1-" + hashlib.sha256(
            _canonical(payload).encode("utf-8")
        ).hexdigest()
        return cls(
            trade_date=day, expected_previous_session=previous,
            feature_as_of=timestamp.isoformat(), previous_context=rows,
            confirmation_features=features,
            previous_context_id=previous_context_id, context_id=context_id,
            input_snapshot_id=str(input_snapshot_id),
        )

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "trade_date": self.trade_date,
            "expected_previous_session": self.expected_previous_session,
            "feature_as_of": self.feature_as_of,
            "previous_context": _thaw(self.previous_context),
            "confirmation_features": _thaw(self.confirmation_features),
            "previous_context_id": self.previous_context_id,
            "context_id": self.context_id,
        }
        if self.input_snapshot_id:
            value["input_snapshot_id"] = self.input_snapshot_id
        return value

    def save(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = self.load(target)
            if existing.context_id != self.context_id:
                raise ValueError("feature context is immutable")
            return target
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                self.to_dict(), ensure_ascii=False, indent=2, allow_nan=False
            ), encoding="utf-8"
        )
        temporary.replace(target)
        return target

    @classmethod
    def load(cls, path: Path | str) -> "FeatureContextV1":
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if value.get("schema_version") != FEATURE_CONTEXT_VERSION:
            raise ValueError("feature context schema mismatch")
        rebuilt = cls.build(
            trade_date=value["trade_date"],
            expected_previous_session=value["expected_previous_session"],
            feature_as_of=value["feature_as_of"],
            previous_context=value["previous_context"],
            confirmation_features=value["confirmation_features"],
            input_snapshot_id=value.get("input_snapshot_id", ""),
        )
        if value.get("context_id") != rebuilt.context_id:
            raise ValueError("feature context content hash mismatch")
        if value.get("previous_context_id") != rebuilt.previous_context_id:
            raise ValueError("previous context content hash mismatch")
        return rebuilt
