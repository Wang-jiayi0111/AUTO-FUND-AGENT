from __future__ import annotations

from datetime import date, datetime

import exchange_calendars as xcals


_calendar = xcals.get_calendar("XSHG")


def is_trading_day(day: date | datetime | None = None) -> bool:
    target = day or date.today()
    if isinstance(target, datetime):
        target = target.date()
    return _calendar.is_session(target.strftime("%Y-%m-%d"))
