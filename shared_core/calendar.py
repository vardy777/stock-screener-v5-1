"""V5-owned verified local exchange calendar reader."""
from __future__ import annotations
import csv
from datetime import date
from pathlib import Path
from .trading_calendar_contract import validate_calendar_records
from .core import ContractViolation

DEFAULT_PATH=Path(__file__).resolve().parent/"reference"/"trading_calendar_cn.csv"
class TradingCalendar:
    def __init__(self,path=DEFAULT_PATH):
        try:
            with Path(path).open("r",encoding="utf-8-sig",newline="") as handle:rows=list(csv.DictReader(handle))
        except OSError as exc:raise ContractViolation("V5 trading calendar missing") from exc
        verified,self.sessions,self.metadata=validate_calendar_records(rows)
        if not verified:raise ContractViolation(f"V5 trading calendar invalid: {self.metadata.get('error','unknown')}")
    def is_open(self,day:date):return self.sessions.get(day.isoformat())
    def next_open(self,day:date):
        values=[date.fromisoformat(value) for value,is_open in self.sessions.items() if is_open and value>day.isoformat()]
        if not values:raise ContractViolation("V5 next trading session unavailable")
        return min(values)

