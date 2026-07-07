from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

TOKYO = ZoneInfo("Asia/Tokyo")
MARKET_CLOSE_JST = time(15, 30)


def _as_fraction(value: float | None) -> float | None:
    """Normalize a ratio to fraction form (0.08 = 8%).

    yfinance has historically flipped some fields between fraction and percent
    across versions; ratios like ROE/growth/payout are practically never above
    300% as a fraction, so larger magnitudes are treated as percents.
    """
    if value is None:
        return None
    return value / 100 if abs(value) > 3 else value


def _yield_as_percent(value: float | None) -> float | None:
    """Normalize a dividend yield to percent form (4.24 = 4.24%).

    Fraction-form yields (0.0424) are far below any plausible percent-form
    yield, so values under 0.25 are treated as fractions.
    """
    if value is None:
        return None
    return value * 100 if abs(value) < 0.25 else value


def _debt_to_equity_as_percent(value: float | None) -> float | None:
    """Normalize debt-to-equity to percent form (80 = 0.8x), which the scoring assumes."""
    if value is None:
        return None
    return value * 100 if abs(value) < 5 else value


def _to_date(value) -> date | None:
    """Coerce yfinance date representations (epoch seconds, date, ISO string) to a date."""
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).date()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str) and value:
            return date.fromisoformat(value[:10])
    except (ValueError, OverflowError, OSError):
        return None
    return None


def fetch_price_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    """Fetch daily OHLCV history for `symbol` over the given period."""
    return yf.Ticker(symbol).history(period=period)


def fetch_fundamentals(symbol: str) -> dict[str, float | str | None]:
    """Fetch valuation, profitability, dividend, and sector metrics for `symbol`.

    Missing fields are None. All ratios are normalized to fixed units on the way in
    (yields/debt-to-equity in percent, ROE/ROA/growth/payout as fractions) so a
    yfinance version change cannot silently flip every judgment.
    """
    info = yf.Ticker(symbol).info

    # Deriving the yield from rate/price avoids the fraction-vs-percent ambiguity entirely.
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    dividend_rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate")
    if dividend_rate and price:
        dividend_yield = dividend_rate / price * 100
    else:
        dividend_yield = _yield_as_percent(info.get("dividendYield"))

    return {
        "name": info.get("longName") or info.get("shortName"),
        "per": info.get("trailingPE"),
        "forward_per": info.get("forwardPE"),
        "pbr": info.get("priceToBook"),
        "dividend_yield": dividend_yield,
        "dividend_rate": dividend_rate,
        "ex_dividend_date": _to_date(info.get("exDividendDate")),
        "roe": _as_fraction(info.get("returnOnEquity")),
        "roa": _as_fraction(info.get("returnOnAssets")),
        "eps": info.get("trailingEps"),
        "bps": info.get("bookValue"),
        "revenue_growth": _as_fraction(info.get("revenueGrowth")),
        "earnings_growth": _as_fraction(info.get("earningsGrowth")),
        "payout_ratio": _as_fraction(info.get("payoutRatio")),
        "debt_to_equity": _debt_to_equity_as_percent(info.get("debtToEquity")),
        "current_ratio": info.get("currentRatio"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        # アナリストのコンセンサス。適正価格・長期期待リターンの一材料に使う。
        # 取得できない銘柄も多いので欠損(None)前提で扱う。
        "target_mean_price": info.get("targetMeanPrice"),
        "target_median_price": info.get("targetMedianPrice"),
        "target_high_price": info.get("targetHighPrice"),
        "target_low_price": info.get("targetLowPrice"),
        "num_analysts": info.get("numberOfAnalystOpinions"),
        "recommendation_mean": info.get("recommendationMean"),
    }


DEFAULT_DIVIDEND_INTERVAL_DAYS = 182  # Japanese dividends are typically semi-annual


def estimate_next_ex_dividend(
    reported: date | None, dividend_dates: list[date], today: date
) -> tuple[date | None, bool]:
    """Return (ex_dividend_date, is_estimated).

    Yahoo keeps returning the *previous* ex-dividend date until the next one is
    announced, so a past date would otherwise sit on the cards for months. When
    the reported date is stale, project the next one from the stock's own payout
    rhythm (median interval between historical ex-dates).
    """
    if reported is not None and reported >= today:
        return reported, False

    dates = sorted(dividend_dates)
    last = dates[-1] if dates else None
    if reported is not None and (last is None or reported > last):
        last = reported
    if last is None:
        return reported, False

    if len(dates) >= 2:
        intervals = sorted((dates[i + 1] - dates[i]).days for i in range(len(dates) - 1))
        step = max(intervals[len(intervals) // 2], 28)
    else:
        step = DEFAULT_DIVIDEND_INTERVAL_DAYS

    projected = last
    for _ in range(24):
        projected += timedelta(days=step)
        if projected >= today:
            return projected, True
    return reported, False


def split_confirmed_history(
    history: pd.DataFrame, now: datetime | None = None
) -> tuple[pd.DataFrame, float | None]:
    """Split price history into (confirmed daily bars, latest price).

    RSI/SMA/MACD assume completed sessions; during trading hours the last row is
    today's still-forming bar, which makes a midday run and an evening run
    disagree for no real reason. Drop that bar from the indicator series but
    keep its close as the display price.
    """
    if history is None or len(history) == 0:
        return history, None

    current_price = float(history["Close"].iloc[-1])
    now = now or datetime.now(TOKYO)
    last = history.index[-1]
    last_date = last.date() if hasattr(last, "date") else None
    if last_date == now.date() and now.time() < MARKET_CLOSE_JST:
        return history.iloc[:-1], current_price
    return history, current_price


def fetch_next_earnings_date(symbol: str) -> date | None:
    """Fetch the next scheduled earnings date for `symbol`, if available."""
    calendar = yf.Ticker(symbol).calendar
    if not calendar:
        return None

    earnings_dates = calendar.get("Earnings Date") if isinstance(calendar, dict) else None
    if not earnings_dates:
        return None

    next_date = earnings_dates[0]
    return next_date if isinstance(next_date, date) else datetime.strptime(str(next_date), "%Y-%m-%d").date()
