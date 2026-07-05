from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

from stock_analyzer.data_fetcher import fetch_fundamentals, split_confirmed_history
from stock_analyzer.indicators import (
    bollinger_sigma,
    evaluate_macd,
    evaluate_volume_price,
    macd,
    rate_of_change,
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
    raw_score: int  # uncapped, used for ranking so strong movers separate from ties at 100
    reasons: list[str]
    current_price: float | None

    @property
    def score(self) -> int:
        """The 0-100 score shown to the user (the raw score clamped)."""
        return _clamp(self.raw_score)


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
    """Score a ticker's short-term swing potential from technicals only.

    Returns (raw_score, reasons) where raw_score is uncapped (can exceed 100) so
    that strong movers can be ranked apart from ordinary ones, and reasons are the
    strongest bullish factors. Returns None if there is not enough history to judge.
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

    roc = rate_of_change(closes, 10)
    if roc is not None:
        if roc >= 10:
            signals.append((10, f"直近10日で+{roc:.0f}%の強い上昇"))
        elif roc >= 3:
            signals.append((5, f"直近10日で+{roc:.0f}%上昇"))
        elif roc <= -10:
            signals.append((-10, f"直近10日で{roc:.0f}%下落"))
        elif roc <= -3:
            signals.append((-5, "直近10日で下落"))

    raw_score = 50 + sum(points for points, _ in signals)
    reasons = [reason for points, reason in sorted(signals, key=lambda s: s[0], reverse=True) if points > 0]
    return raw_score, reasons[:4]


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
        confirmed, current_price = split_confirmed_history(frame)
        if confirmed is None or len(confirmed) < MIN_HISTORY:
            continue

        closes = confirmed["Close"].tolist()
        highs = confirmed["High"].tolist()
        lows = confirmed["Low"].tolist()
        volumes = confirmed["Volume"].tolist()

        result = swing_score(closes, highs, lows, volumes)
        if result is None:
            continue
        raw_score, reasons = result
        candidates.append(
            SwingCandidate(
                symbol=ticker, raw_score=raw_score, reasons=reasons, current_price=current_price
            )
        )

    return candidates


def top_swing_picks(tickers: list[str] | None = None, n: int = 3) -> list[SwingCandidate]:
    """Return the top `n` swing candidates, ranked by uncapped raw score, best first."""
    universe = tickers if tickers is not None else load_universe()
    candidates = screen_universe(universe)
    candidates.sort(key=lambda c: c.raw_score, reverse=True)
    return candidates[:n]


def top_swing_pick(tickers: list[str] | None = None) -> SwingCandidate | None:
    """Return the single highest-scoring swing candidate, or None if none qualify."""
    picks = top_swing_picks(tickers, n=1)
    return picks[0] if picks else None


def _price(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.0f}円"
    return f"{value:,.2f}"


RANK_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
DISCLAIMER = "※保有していない銘柄です。機械的スコアによる候補であり、値上がりを保証するものではありません。投資は自己責任で。"


def format_swing_picks(candidates: list[SwingCandidate]) -> str:
    """Render the top swing candidates as one compact LINE section, fetching each name."""
    lines = ["━━━━━━━━━━━━", "🔎 本日の注目候補（スイング）TOP3"]

    for index, candidate in enumerate(candidates):
        try:
            name = fetch_fundamentals(candidate.symbol)["name"]
        except Exception:
            name = None
        heading = f"{candidate.symbol} {name}" if name else candidate.symbol
        rank = RANK_EMOJI[index] if index < len(RANK_EMOJI) else f"{index + 1}."

        lines.append("")
        lines.append(f"{rank}【{heading}】 {candidate.score}点")
        lines.append(f"現在：{_price(candidate.current_price)}")
        lines.extend(f"・{reason}" for reason in candidate.reasons)

    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("━━━━━━━━━━━━")
    return "\n".join(lines)


def build_swing_section() -> list[str]:
    """Scan the universe and return the formatted top-3 swing-pick lines, or an empty list."""
    picks = top_swing_picks()
    if not picks:
        return []
    return [format_swing_picks(picks)]
