from __future__ import annotations

import pandas as pd
import yfinance as yf


def fetch_price_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    """Fetch daily OHLCV history for `symbol` over the given period."""
    return yf.Ticker(symbol).history(period=period)


def fetch_fundamentals(symbol: str) -> dict[str, float | None]:
    """Fetch PER, PBR, and dividend yield for `symbol`. Missing fields are None."""
    info = yf.Ticker(symbol).info
    return {
        "per": info.get("trailingPE"),
        "pbr": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
    }
