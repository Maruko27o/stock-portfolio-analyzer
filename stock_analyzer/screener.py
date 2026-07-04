from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

from stock_analyzer.data_fetcher import fetch_fundamentals
from stock_analyzer.indicators import (
    bollinger_sigma,
    evaluate_macd,
    evaluate_volume_price,
    macd,
    relative_strength_index,
    simple_moving_average,
    support_resistance,
    volume_trend,
)

UNIVERSE_FILE = Path(__file__).parent / "data" / "nikkei225.txt"
MIN_HISTORY = 30


@dataclass
class SwingCandidate:
    symbol: str
    score: int
    reasons: list[str]
    current_price: float | None


def load_universe(path: Path = UNIVERSE_FILE) -> list[str]:
    """Load the list of tickers to screen, ignoring comments and blank lines."""
    tickers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tickers.append(line.upper())
    return tickers


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def swing_score(
    closes: list[float], highs: list[float], lows: list[float], volumes: list[float]
) -> tuple[int, list[str]] | None:
    """Score a ticker's short-term swing potential (0-100) from technicals only.

    Returns (score, reasons) where reasons are the strongest bullish factors, or
    None if there is not enough history to judge.
    """
    if len(closes) < MIN_HISTORY:
        return None

    price = closes[-1]
    signals: list[tuple[int, str]] = []

    sma5 = simple_moving_average(closes, 5)
    sma25 = simple_moving_average(closes, 25)
    sma25_prev = simple_moving_average(closes[:-1], 25)
    if sma25 is not None and sma25_prev is not None:
        if price > sma25 and sma25 > sma25_prev:
            signals.append((12, "25日線を上回り上昇中"))
        elif price < sma25:
            signals.append((-12, "25日線を下回る"))
    if sma5 is not None and sma25 is not None and sma5 > sma25:
        signals.append((8, "短期線が中期線を上回る"))

    macd_signal = evaluate_macd(macd(closes))
    if macd_signal == "ゴールデンクロス":
        signals.append((15, "MACDゴールデンクロス"))
    elif macd_signal == "上昇中":
        signals.append((8, "MACD上昇中"))
    elif macd_signal == "デッドクロス":
        signals.append((-15, "MACDデッドクロス"))
    elif macd_signal == "下降中":
        signals.append((-8, "MACD下降中"))

    rsi = relative_strength_index(closes, 14)
    if rsi is not None:
        if 50 <= rsi <= 65:
            signals.append((10, f"RSI{rsi:.0f}で上昇余地あり"))
        elif 65 < rsi < 75:
            signals.append((3, f"RSI{rsi:.0f}"))
        elif rsi >= 75:
            signals.append((-12, f"RSI{rsi:.0f}で過熱"))
        elif 40 <= rsi < 50:
            signals.append((5, f"RSI{rsi:.0f}で回復基調"))
        elif rsi <= 30:
            signals.append((6, f"RSI{rsi:.0f}で売られすぎ反発期待"))

    volume_price = evaluate_volume_price(closes, volumes)
    if "強い上昇" in volume_price:
        signals.append((12, "出来高増加を伴う上昇"))
    elif "勢い弱い" in volume_price:
        signals.append((-3, "上昇も出来高が細る"))
    elif "強い下落" in volume_price:
        signals.append((-12, "出来高増加を伴う下落"))

    vt = volume_trend(volumes)
    if vt is not None:
        if vt >= 1.2:
            signals.append((8, "出来高が増加傾向"))
        elif vt <= 0.8:
            signals.append((-4, "出来高が減少傾向"))

    levels = support_resistance(highs, lows)
    if levels is not None and price >= levels.resistance * 0.98:
        signals.append((10, "レジスタンス突破間近"))

    boll = bollinger_sigma(closes)
    if boll is not None:
        if 1 <= boll < 2.5:
            signals.append((5, "上昇局面(バンド上方)"))
        elif boll >= 2.5:
            signals.append((-8, "バンド上限で過熱"))
        elif boll <= -2:
            signals.append((3, "バンド下限で反発期待"))

    score = _clamp(50 + sum(points for points, _ in signals))
    reasons = [reason for points, reason in sorted(signals, key=lambda s: s[0], reverse=True) if points > 0]
    return score, reasons[:4]


def _download_history(tickers: list[str], period: str = "6mo"):
    """Bulk-download OHLCV history for many tickers in a single request."""
    return yf.download(
        tickers,
        period=period,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )


def screen_universe(tickers: list[str]) -> list[SwingCandidate]:
    """Score every ticker that has usable data, skipping any that fail to download."""
    data = _download_history(tickers)
    candidates: list[SwingCandidate] = []

    for ticker in tickers:
        try:
            frame = data[ticker].dropna()
        except (KeyError, TypeError):
            continue
        if len(frame) < MIN_HISTORY:
            continue

        closes = frame["Close"].tolist()
        highs = frame["High"].tolist()
        lows = frame["Low"].tolist()
        volumes = frame["Volume"].tolist()

        result = swing_score(closes, highs, lows, volumes)
        if result is None:
            continue
        score, reasons = result
        candidates.append(
            SwingCandidate(symbol=ticker, score=score, reasons=reasons, current_price=closes[-1])
        )

    return candidates


def top_swing_pick(tickers: list[str] | None = None) -> SwingCandidate | None:
    """Return the single highest-scoring swing candidate, or None if none qualify."""
    universe = tickers if tickers is not None else load_universe()
    candidates = screen_universe(universe)
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.score)


def _price(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.0f}円"
    return f"{value:,.2f}"


def format_swing_pick(candidate: SwingCandidate) -> str:
    """Render the swing pick as a compact LINE section, fetching the company name."""
    try:
        name = fetch_fundamentals(candidate.symbol)["name"]
    except Exception:
        name = None

    heading = f"{candidate.symbol} {name}" if name else candidate.symbol
    lines = [
        "━━━━━━━━━━━━",
        "🔎 本日の注目候補（スイング）",
        f"【{heading}】",
        f"現在：{_price(candidate.current_price)}",
        f"スコア：{candidate.score}点",
    ]
    lines.extend(f"・{reason}" for reason in candidate.reasons)
    lines.append("※保有していない銘柄です。機械的スコアによる候補であり、値上がりを保証するものではありません。投資は自己責任で。")
    lines.append("━━━━━━━━━━━━")
    return "\n".join(lines)


def build_swing_section() -> list[str]:
    """Scan the universe and return the formatted swing-pick lines, or an empty list."""
    pick = top_swing_pick()
    if pick is None:
        return []
    return [format_swing_pick(pick)]
