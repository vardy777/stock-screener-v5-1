from datetime import date
from v5.calendar import TradingCalendar
def test_v5_calendar_is_owned_verified_and_covers_buy_to_next_session():
 calendar=TradingCalendar();assert calendar.is_open(date(2026,8,14)) is True and calendar.next_open(date(2026,8,14))==date(2026,8,17)
