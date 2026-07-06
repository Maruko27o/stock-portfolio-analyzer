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
US10Y_TICKER = "^TNX"  # 米10年国債利回り(長期金利の代理。yfinance では利回りをそのまま数値化)

# 市場全体の強弱(breadth)判定から除く、株価指数でない系列。
NON_EQUITY_NAMES = {"ドル円", "VIX", "長期金利"}


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
    named_tickers = list(INDEX_TICKERS.items()) + [
        ("ドル円", FX_TICKER),
        ("VIX", VIX_TICKER),
        ("長期金利", US10Y_TICKER),
    ]
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
        if name not in NON_EQUITY_NAMES and change is not None
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


def market_stance(
    snapshot: dict[str, tuple[float | None, float | None]], vix: float | None = None
) -> str:
    """市場全体を5段階(強気/やや強気/中立/やや弱気/弱気)へ分類する。

    株価指数の上昇/下落の数(breadth)と平均変化率の大きさから素点を作り、
    VIX が高い(リスクオフ)ときは弱気側へ補正する。yfinance で取れない
    騰落レシオ・新高値新安値・セクターローテーションは加味しない(捏造しない)。
    """
    changes = [
        change
        for name, (_, change) in snapshot.items()
        if name not in NON_EQUITY_NAMES and change is not None
    ]
    if not changes:
        return "中立"

    positive = sum(1 for c in changes if c > 0)
    negative = sum(1 for c in changes if c < 0)
    breadth = positive - negative  # 上昇数−下落数
    avg = sum(changes) / len(changes)  # 平均変化率(%)

    score = breadth + avg  # 数と強さの合成
    if vix is not None and vix >= 25:
        score -= 1  # 警戒〜リスクオフは弱気側へ

    if score >= 3:
        return "強気"
    if score >= 1:
        return "やや強気"
    if score > -1:
        return "中立"
    if score > -3:
        return "やや弱気"
    return "弱気"
