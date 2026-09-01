"""Frozen production policy for Security Master verification cycles."""
from datetime import date
from shared_core.calendar import TradingCalendar
from shared_core.core import ContractViolation

def allowed_master_verification_dates(trade_date,calendar):
    if not isinstance(calendar,TradingCalendar):raise ContractViolation("verified TradingCalendar required")
    day=date.fromisoformat(str(trade_date))
    if calendar.is_open(day) is not True:raise ContractViolation("master verification trade date must be open session")
    previous=sorted(value for value,is_open in calendar.sessions.items() if is_open and value<day.isoformat())
    if not previous:raise ContractViolation("previous completed verification cycle unavailable")
    return frozenset((previous[-1],day.isoformat()))
