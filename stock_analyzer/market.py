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


def _change_from_closes(closes: list[float]) -> tuple[float | None, float | None]:
    """Return (current price, daily % change) from a list of closing prices."""
    if not closes:
        return None, None
    if len(closes) < 2:
        return closes[-1], None

    current, previous = closes[-1], closes[-2]
    change_pct = (current - previous) / previous * 100 if previous else None
    return current, change_pct


def fetch_market_snapshot() -> dict[str, tuple[float | None, float | None]]:
    """Fetch current price and daily % change for major indices, USD/JPY, and VIX.

    All tickers are pulled in a single bulk download instead of one request each.
    """
    named_tickers = list(INDEX_TICKERS.items()) + [("ドル円", FX_TICKER), ("VIX", VIX_TICKER)]
    data = yf.download(
        [ticker for _, ticker in named_tickers],
        period="5d",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    snapshot: dict[str, tuple[float | None, float | None]] = {}
    for name, ticker in named_tickers:
        try:
            closes = data[ticker]["Close"].dropna().tolist()
        except (KeyError, TypeError):
            closes = []
        snapshot[name] = _change_from_closes(closes)
    return snapshot


def classify_regime(n225_closes) -> "pd.Series":
    """日経平均の終値系列から相場環境(上昇/下落/横ばい)を日次で判定する。

    200日線の上で直近60日+3%超なら上昇、下で-3%未満なら下落、他は横ばい。
    """
    import numpy as np
    import pandas as pd

    closes = n225_closes
    sma200 = closes.rolling(200).mean()
    roc60 = (closes / closes.shift(60) - 1) * 100
    regime = pd.Series("横ばい", index=closes.index)
    regime[(closes > sma200) & (roc60 > 3)] = "上昇"
    regime[(closes < sma200) & (roc60 < -3)] = "下落"
    regime[sma200.isna()] = "横ばい"
    return regime


def current_market_regime() -> str | None:
    """現在の相場環境を返す(判定不能ならNone)。"""
    try:
        history = yf.Ticker("^N225").history(period="2y")
        closes = history["Close"].dropna()
        if len(closes) < 260:
            return None
        return str(classify_regime(closes).iloc[-1])
    except Exception:
        return None


def vix_regime_label(vix: float | None) -> str:
    """Classify the VIX level into a plain-language market-stress label."""
    if vix is None:
        return "データ不足"
    if vix >= 30:
        return "リスクオフ"
    if vix >= 25:
        return "警戒"
    if vix > 20:
        return "やや不安定"
    if vix >= 15:
        return "平常"
    return "安定"


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
