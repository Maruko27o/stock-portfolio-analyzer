from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf


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
    """Fetch valuation, profitability, dividend, and sector metrics for `symbol`. Missing fields are None."""
    info = yf.Ticker(symbol).info
    return {
        "name": info.get("longName") or info.get("shortName"),
        "per": info.get("trailingPE"),
        "pbr": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "dividend_rate": info.get("dividendRate") or info.get("trailingAnnualDividendRate"),
        "ex_dividend_date": _to_date(info.get("exDividendDate")),
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "eps": info.get("trailingEps"),
        "bps": info.get("bookValue"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "payout_ratio": info.get("payoutRatio"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
    }


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
