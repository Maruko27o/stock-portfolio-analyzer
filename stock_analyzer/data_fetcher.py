from __future__ import annotations

import yfinance as yf


def fetch_closing_prices(symbol: str, period: str = "3mo") -> list[float]:
    """Fetch daily closing prices for `symbol` over the given period."""
    history = yf.Ticker(symbol).history(period=period)
    return history["Close"].tolist()
