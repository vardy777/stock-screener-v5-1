"""Validated handoff contract between exact-time feature jobs and V4 scoring."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from phase1.overnight.dataset import FEATURE_COLUMNS

from .execution import CHINA_TZ, TradingClock


ROOT = Path(__file__).resolve().parent.parent
STORE_PATH = ROOT / "v4" / "data" / "live_features.json"


class LiveFeatureStore:
    @staticmethod
    def publish(rows: Dict[str, Dict[str, Any]], *, as_of: Optional[datetime] = None) -> None:
        timestamp = as_of or TradingClock.now()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=CHINA_TZ)
        clean = {}
        for code, features in rows.items():
            missing = [name for name in FEATURE_COLUMNS if name not in features]
            if missing:
                continue
            clean[str(code).zfill(6)] = {
                name: features.get(name) for name in FEATURE_COLUMNS
            }
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = STORE_PATH.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(
                {"as_of": timestamp.isoformat(), "rows": clean},
                handle,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        temporary.replace(STORE_PATH)

    @staticmethod
    def load_all(
        *, maximum_age_seconds: int = 120, now: Optional[datetime] = None
    ) -> Dict[str, Dict[str, Any]]:
        try:
            with STORE_PATH.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            as_of = datetime.fromisoformat(payload["as_of"])
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=CHINA_TZ)
            current = now or TradingClock.now()
            if current.tzinfo is None:
                current = current.replace(tzinfo=CHINA_TZ)
            age = (
                current.astimezone(CHINA_TZ) - as_of.astimezone(CHINA_TZ)
            ).total_seconds()
            # Future-dated features are non-causal.  Do not use abs(age): that
            # would silently accept a feature snapshot created after a decision.
            if not 0 <= age <= maximum_age_seconds:
                return {}
            rows = payload.get("rows", {})
            if not isinstance(rows, dict):
                return {}
            return {
                str(code).zfill(6): features
                for code, features in rows.items()
                if isinstance(features, dict)
                and all(name in features for name in FEATURE_COLUMNS)
            }
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    @staticmethod
    def get(code: str, *, maximum_age_seconds: int = 120) -> Optional[Dict[str, Any]]:
        return LiveFeatureStore.load_all(
            maximum_age_seconds=maximum_age_seconds
        ).get(str(code).zfill(6))
