"""Clock and quote-freshness controls for V4 execution adapters."""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from .contracts import ActionStatus
from .calendar import TradingCalendar


CHINA_TZ = ZoneInfo("Asia/Shanghai")


class ExecutionBlocked(RuntimeError):
    """Raised when an execution request violates a hard V4 safety gate."""


class TradingClock:
    SIGNAL_START = time(14, 49, 0)
    SIGNAL_END = time(14, 49, 59)
    BUY_START = time(14, 50, 0)
    BUY_END = time(14, 51, 59)
    SELL_START = time(9, 30, 0)
    SELL_END = time(9, 35, 0)
    CALENDAR = TradingCalendar()

    @classmethod
    def now(cls) -> datetime:
        return datetime.now(CHINA_TZ)

    @classmethod
    def action_status(
        cls, action: str, *, now: Optional[datetime] = None
    ) -> ActionStatus:
        current = now or cls.now()
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        current = current.astimezone(CHINA_TZ)

        action = action.lower()
        if action == "signal":
            start, end, window = cls.SIGNAL_START, cls.SIGNAL_END, "14:49:00-14:49:59"
        elif action == "buy":
            start, end, window = cls.BUY_START, cls.BUY_END, "14:50:00-14:51:59"
        elif action == "sell":
            start, end, window = cls.SELL_START, cls.SELL_END, "09:30:00-09:35:00"
        else:
            return ActionStatus(action, False, "未知交易动作", "--", current.isoformat())

        if current.weekday() >= 5:
            return ActionStatus(action, False, "周末休市", window, current.isoformat())
        calendar_open = cls.CALENDAR.is_open(current.date())
        if calendar_open is None:
            return ActionStatus(
                action, False, "交易日历缺失、未核验或未覆盖", window, current.isoformat()
            )
        if not calendar_open:
            return ActionStatus(action, False, "交易所公告休市", window, current.isoformat())
        allowed = start <= current.time().replace(tzinfo=None) <= end
        reason = "处于允许窗口" if allowed else f"不在{window}执行窗口"
        return ActionStatus(action, allowed, reason, window, current.isoformat())

    @classmethod
    def require(cls, action: str, *, force: bool = False) -> ActionStatus:
        status = cls.action_status(action)
        if not status.allowed and not force:
            raise ExecutionBlocked(status.reason)
        return status

    @classmethod
    def quote_is_fresh(
        cls,
        quote_time,
        *,
        now: Optional[datetime] = None,
        maximum_age_seconds: int = 30,
    ) -> bool:
        if quote_time in (None, ""):
            return False
        current = now or cls.now()
        if current.tzinfo is None:
            return False
        try:
            parsed = datetime.fromisoformat(str(quote_time))
        except (TypeError, ValueError):
            return False
        if parsed.tzinfo is None:
            return False
        age = (
            current.astimezone(CHINA_TZ) - parsed.astimezone(CHINA_TZ)
        ).total_seconds()
        # A quote timestamp later than the capture timestamp is non-causal and
        # must never enter a strict point-in-time sample.
        return 0 <= age <= maximum_age_seconds
