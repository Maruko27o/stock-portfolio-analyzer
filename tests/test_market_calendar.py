from datetime import date

from stock_analyzer.market_calendar import is_market_closed


def test_weekends_are_closed():
    assert is_market_closed(date(2026, 7, 4))  # Saturday
    assert is_market_closed(date(2026, 7, 5))  # Sunday


def test_public_holidays_are_closed():
    assert is_market_closed(date(2026, 7, 20))  # 海の日(第3月曜)
    assert is_market_closed(date(2026, 2, 11))  # 建国記念の日


def test_year_end_closures():
    assert is_market_closed(date(2026, 12, 31))
    assert is_market_closed(date(2027, 1, 2))  # Saturday anyway, but also TSE closure
    assert is_market_closed(date(2026, 1, 2))  # Friday but TSE is closed


def test_ordinary_weekday_is_open():
    assert not is_market_closed(date(2026, 7, 6))  # Monday
    assert not is_market_closed(date(2026, 7, 21))  # Tuesday after 海の日
