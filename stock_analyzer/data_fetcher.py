from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import yfinance as yf


def fetch_price_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    """Fetch daily OHLCV history for `symbol` over the given period."""
    return yf.Ticker(symbol).history(period=period)


def fetch_fundamentals(symbol: str) -> dict[str, float | None]:
    """Fetch valuation, profitability, and dividend metrics for `symbol`. Missing fields are None."""
    info = yf.Ticker(symbol).info
    return {
        "per": info.get("trailingPE"),
        "pbr": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "eps": info.get("trailingEps"),
        "bps": info.get("bookValue"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "payout_ratio": info.get("payoutRatio"),
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
