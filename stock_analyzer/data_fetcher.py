from __future__ import annotations

import yfinance as yf


def fetch_closing_prices(symbol: str, period: str = "3mo") -> list[float]:
    """Fetch daily closing prices for `symbol` over the given period."""
    history = yf.Ticker(symbol).history(period=period)
    return history["Close"].tolist()


def fetch_fundamentals(symbol: str) -> dict[str, float | None]:
    """Fetch PER, PBR, and dividend yield for `symbol`. Missing fields are None."""
    info = yf.Ticker(symbol).info
    return {
        "per": info.get("trailingPE"),
        "pbr": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
    }
