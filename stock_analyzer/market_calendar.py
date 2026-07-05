from __future__ import annotations

from datetime import date

import jpholiday

# TSE closes over year-end/new-year in addition to public holidays.
EXCHANGE_EXTRA_HOLIDAYS = ((1, 1), (1, 2), (1, 3), (12, 31))


def is_market_closed(day: date) -> bool:
    """True on weekends, Japanese public holidays, and TSE year-end closures."""
    if day.weekday() >= 5:
        return True
    if (day.month, day.day) in EXCHANGE_EXTRA_HOLIDAYS:
        return True
    return bool(jpholiday.is_holiday(day))
