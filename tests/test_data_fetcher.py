from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.data_fetcher import (
    _as_fraction,
    _debt_to_equity_as_percent,
    _to_date,
    _yield_as_percent,
    estimate_next_ex_dividend,
    split_confirmed_history,
)

TOKYO = ZoneInfo("Asia/Tokyo")


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


def test_as_fraction_normalizes_percent_form():
    assert _as_fraction(0.08) == 0.08  # already a fraction
    assert _as_fraction(8.0) == 0.08  # percent form gets divided
    assert _as_fraction(-12.0) == -0.12
    assert _as_fraction(None) is None


def test_yield_as_percent_normalizes_fraction_form():
    assert _yield_as_percent(4.24) == 4.24  # already percent
    assert _yield_as_percent(0.0424) == 4.24  # fraction form gets multiplied
    assert _yield_as_percent(None) is None


def test_debt_to_equity_as_percent():
    assert _debt_to_equity_as_percent(80.0) == 80.0  # percent form kept
    assert _debt_to_equity_as_percent(0.8) == 80.0  # ratio form scaled
    assert _debt_to_equity_as_percent(None) is None


def _history(last_day: date) -> pd.DataFrame:
    days = pd.date_range(end=pd.Timestamp(last_day, tz="Asia/Tokyo"), periods=5, freq="B")
    return pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0, 103.0, 104.0]},
        index=days,
    )


def test_split_confirmed_history_drops_todays_bar_during_session():
    history = _history(date(2026, 7, 6))
    midday = datetime(2026, 7, 6, 13, 0, tzinfo=TOKYO)
    confirmed, current_price = split_confirmed_history(history, now=midday)
    assert current_price == 104.0  # display price is still the latest
    assert len(confirmed) == 4  # but indicators exclude the forming bar
    assert confirmed["Close"].tolist()[-1] == 103.0


def test_split_confirmed_history_keeps_todays_bar_after_close():
    history = _history(date(2026, 7, 6))
    evening = datetime(2026, 7, 6, 21, 0, tzinfo=TOKYO)
    confirmed, current_price = split_confirmed_history(history, now=evening)
    assert current_price == 104.0
    assert len(confirmed) == 5


def test_split_confirmed_history_keeps_all_bars_when_last_is_past_day():
    history = _history(date(2026, 7, 3))
    monday = datetime(2026, 7, 6, 13, 0, tzinfo=TOKYO)
    confirmed, current_price = split_confirmed_history(history, now=monday)
    assert len(confirmed) == 5
    assert current_price == 104.0


def test_estimate_keeps_future_announced_date():
    today = date(2026, 7, 5)
    result = estimate_next_ex_dividend(date(2026, 9, 29), [date(2026, 3, 30)], today)
    assert result == (date(2026, 9, 29), False)


def test_estimate_projects_from_semiannual_history_when_stale():
    today = date(2026, 7, 5)
    # Yahoo still reports the March ex-date; history shows a ~6-month rhythm.
    history = [date(2025, 3, 28), date(2025, 9, 29), date(2026, 3, 30)]
    projected, estimated = estimate_next_ex_dividend(date(2026, 3, 30), history, today)
    assert estimated is True
    assert projected >= today
    assert date(2026, 9, 1) <= projected <= date(2026, 10, 31)  # roughly next半期末


def test_estimate_defaults_to_semiannual_with_single_known_date():
    today = date(2026, 7, 5)
    projected, estimated = estimate_next_ex_dividend(date(2026, 3, 30), [], today)
    assert estimated is True
    assert projected == date(2026, 3, 30) + __import__("datetime").timedelta(days=182)


def test_estimate_returns_reported_when_nothing_to_project_from():
    assert estimate_next_ex_dividend(None, [], date(2026, 7, 5)) == (None, False)


def test_split_confirmed_history_empty():
    empty = pd.DataFrame({"Close": []})
    confirmed, current_price = split_confirmed_history(empty)
    assert current_price is None
    assert len(confirmed) == 0
