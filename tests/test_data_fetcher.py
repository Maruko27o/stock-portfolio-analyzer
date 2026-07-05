from datetime import date, datetime

from stock_analyzer.data_fetcher import _to_date


def test_to_date_parses_epoch_seconds():
    assert _to_date(1785369600) == date(2026, 7, 30)


def test_to_date_passes_through_dates_and_datetimes():
    assert _to_date(date(2026, 7, 30)) == date(2026, 7, 30)
    assert _to_date(datetime(2026, 7, 30, 9, 0)) == date(2026, 7, 30)


def test_to_date_parses_iso_strings():
    assert _to_date("2026-07-30") == date(2026, 7, 30)
    assert _to_date("2026-07-30T00:00:00") == date(2026, 7, 30)


def test_to_date_returns_none_for_missing_or_invalid():
    assert _to_date(None) is None
    assert _to_date("") is None
    assert _to_date("not-a-date") is None
