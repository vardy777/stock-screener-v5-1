"""Verified local A-share trading calendar used by execution safety gates."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Dict, Optional


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CALENDAR_PATH = ROOT / "phase1" / "data" / "trading_calendar_cn.csv"
OFFICIAL_HOSTS = ("sse.com.cn", "szse.cn")


class TradingCalendar:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_CALENDAR_PATH
        self.sessions: Dict[str, bool] = {}
        self.verified = False
        self.source_url = ""
        self._load()

    def _load(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError:
            return
        if not rows or not {"date", "is_open", "source_url", "verified_at"}.issubset(rows[0]):
            return
        sources = {str(row.get("source_url", "")).strip() for row in rows}
        verified_dates = all(str(row.get("verified_at", "")).strip() for row in rows)
        official = bool(sources) and all(
            any(host in source.lower() for host in OFFICIAL_HOSTS)
            for source in sources
        )
        for row in rows:
            day = str(row.get("date", "")).strip()
            if not day:
                continue
            value = str(row.get("is_open", "")).strip().lower()
            self.sessions[day] = value in {"1", "true", "yes"}
        self.verified = bool(self.sessions) and verified_dates and official
        self.source_url = next(iter(sources), "")

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
