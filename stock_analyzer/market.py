from __future__ import annotations

import yfinance as yf

INDEX_TICKERS = {
    "日経平均": "^N225",
    "TOPIX": "1306.T",
    "NYダウ": "^DJI",
    "NASDAQ": "^IXIC",
    "S&P500": "^GSPC",
}
FX_TICKER = "JPY=X"
VIX_TICKER = "^VIX"


def fetch_index_change(ticker: str) -> tuple[float | None, float | None]:
    """Return (current price, daily % change) for `ticker`, or (None, None) if unavailable."""
    closes = yf.Ticker(ticker).history(period="5d")["Close"].tolist()
    if not closes:
        return None, None
    if len(closes) < 2:
        return closes[-1], None

    current, previous = closes[-1], closes[-2]
    change_pct = (current - previous) / previous * 100 if previous else None
    return current, change_pct


def fetch_market_snapshot() -> dict[str, tuple[float | None, float | None]]:
    """Fetch current price and daily % change for major indices, USD/JPY, and VIX."""
    snapshot = {name: fetch_index_change(ticker) for name, ticker in INDEX_TICKERS.items()}
    snapshot["ドル円"] = fetch_index_change(FX_TICKER)
    snapshot["VIX"] = fetch_index_change(VIX_TICKER)
    return snapshot


def evaluate_market_sentiment(snapshot: dict[str, tuple[float | None, float | None]]) -> str:
    """Judge overall market sentiment from how many equity indices rose vs fell today."""
    changes = [
        change
        for name, (_, change) in snapshot.items()
        if name not in ("ドル円", "VIX") and change is not None
    ]
    if not changes:
        return "データ不足"

    positive = sum(1 for c in changes if c > 0)
    negative = sum(1 for c in changes if c < 0)
    if positive > negative:
        return "強気"
    if negative > positive:
        return "弱気"
    return "中立"
