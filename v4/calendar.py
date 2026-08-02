"""Verified local A-share trading calendar used by execution safety gates."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Dict, Optional

from trading_calendar_contract import validate_calendar_records


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CALENDAR_PATH = ROOT / "phase1" / "data" / "trading_calendar_cn.csv"
class TradingCalendar:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_CALENDAR_PATH
        self.sessions: Dict[str, bool] = {}
        self.verified = False
        self.source_url = ""
        self.validation = {}
        self._load()

    def _load(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError:
            return
        verified, sessions, validation = validate_calendar_records(rows)
        self.sessions = sessions
        self.validation = validation
        self.verified = verified
        self.source_url = next(iter(validation.get("source_urls", [])), "")

    def is_open(self, day: date) -> Optional[bool]:
        if not self.verified:
            return None
        return self.sessions.get(day.isoformat())

    def previous_open(self, day: date) -> Optional[date]:
        if not self.verified:
            return None
        candidates = [
            date.fromisoformat(value)
            for value, is_open in self.sessions.items()
            if is_open and value < day.isoformat()
        ]
        return max(candidates) if candidates else None

    def next_open(self, day: date) -> Optional[date]:
        if not self.verified:
            return None
        candidates = [
            date.fromisoformat(value)
            for value, is_open in self.sessions.items()
            if is_open and value > day.isoformat()
        ]
        return min(candidates) if candidates else None
