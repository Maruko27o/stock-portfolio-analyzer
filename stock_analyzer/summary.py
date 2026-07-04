from __future__ import annotations

from dataclasses import dataclass, field

from stock_analyzer.analysis import HoldingAnalysis
from stock_analyzer.indicators import evaluate_macd


@dataclass
class Signal:
    """A single weighted signal contributing to the overall score, with a human-readable reason."""

    points: int
    reason: str


@dataclass
class HoldingSummary:
    symbol: str
    name: str | None
    current_price: float | None
    avg_cost: float
    profit_pct: float | None
    score: int
    raw_score: int  # uncapped score used to order holdings so ties at 100 still sort
    rating: str
    action: str
    take_profit: float | None
    stop_loss: float | None
    add_price: float | None
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def build_signals(analysis: HoldingAnalysis, market_sentiment: str) -> list[Signal]:
    """Turn the raw analysis into a list of weighted, labelled signals."""
    signals: list[Signal] = []
    price = analysis.current_price

    # --- Technical ---
    if price is not None and analysis.sma_mid is not None:
        if price > analysis.sma_mid:
            signals.append(Signal(8, "25日線を上抜け"))
        else:
            signals.append(Signal(-8, "25日線を下回る"))

    if analysis.sma_short is not None and analysis.sma_mid is not None and analysis.sma_long is not None:
        if analysis.sma_short > analysis.sma_mid > analysis.sma_long:
            signals.append(Signal(5, "移動平均線が上昇配列"))
        elif analysis.sma_short < analysis.sma_mid < analysis.sma_long:
            signals.append(Signal(-5, "移動平均線が下降配列"))

    macd_signal = evaluate_macd(analysis.macd_result)
    if macd_signal == "ゴールデンクロス":
        signals.append(Signal(10, "MACDゴールデンクロス"))
    elif macd_signal == "デッドクロス":
        signals.append(Signal(-10, "MACDデッドクロス"))
    elif macd_signal == "上昇中":
        signals.append(Signal(4, "MACD上昇中"))
    elif macd_signal == "下降中":
        signals.append(Signal(-4, "MACD下降中"))

    if analysis.rsi is not None:
        if analysis.rsi <= 30:
            signals.append(Signal(8, f"RSI{analysis.rsi:.0f}で売られすぎ(反発期待)"))
        elif analysis.rsi >= 70:
            signals.append(Signal(-8, f"RSI{analysis.rsi:.0f}で買われすぎ"))

    if "強い上昇" in analysis.volume_price_signal:
        signals.append(Signal(6, "出来高増加を伴う上昇"))
    elif "勢い弱い" in analysis.volume_price_signal:
        signals.append(Signal(-2, "上昇も出来高が細る"))
    elif "強い下落" in analysis.volume_price_signal:
        signals.append(Signal(-6, "出来高増加を伴う下落"))
    elif "下げ渋り" in analysis.volume_price_signal:
        signals.append(Signal(2, "下落だが出来高は減少"))

    if analysis.levels is not None and price is not None:
        if price >= analysis.levels.resistance:
            signals.append(Signal(5, "レジスタンスを突破"))
        elif price <= analysis.levels.support:
            signals.append(Signal(-5, "サポートを割れ"))

    if analysis.bollinger is not None:
        if analysis.bollinger >= 2:
            signals.append(Signal(-3, "ボリンジャーバンド上限で過熱"))
        elif analysis.bollinger <= -2:
            signals.append(Signal(3, "ボリンジャーバンド下限で反発期待"))

    if analysis.momentum is not None:
        if analysis.momentum >= 10:
            signals.append(Signal(6, f"直近10日で+{analysis.momentum:.0f}%の強い上昇"))
        elif analysis.momentum >= 3:
            signals.append(Signal(3, f"直近10日で+{analysis.momentum:.0f}%上昇"))
        elif analysis.momentum <= -10:
            signals.append(Signal(-6, f"直近10日で{analysis.momentum:.0f}%下落"))
        elif analysis.momentum <= -3:
            signals.append(Signal(-3, "直近10日で下落"))

    # --- Fundamental ---
    if analysis.per is not None:
        signals.append(Signal(6, "PER割安") if analysis.per <= 15 else Signal(-3, "PER割高"))
    if analysis.pbr is not None:
        signals.append(Signal(5, "PBR割安") if analysis.pbr <= 1 else Signal(-2, "PBR割高"))
    if analysis.roe is not None:
        signals.append(Signal(6, "ROE良好") if analysis.roe >= 0.08 else Signal(-2, "ROEが低い"))
    if analysis.revenue_growth is not None:
        signals.append(Signal(4, "増収") if analysis.revenue_growth > 0 else Signal(-4, "減収"))
    if analysis.earnings_growth is not None:
        signals.append(Signal(5, "増益") if analysis.earnings_growth > 0 else Signal(-5, "減益"))

    # --- Market ---
    if market_sentiment == "強気":
        signals.append(Signal(5, "市場全体が上昇基調"))
    elif market_sentiment == "弱気":
        signals.append(Signal(-5, "市場全体が下落基調"))

    return signals


def score_from_signals(signals: list[Signal]) -> int:
    return _clamp(50 + sum(s.points for s in signals))


def rating_from_score(score: int) -> str:
    if score >= 85:
        return "◎◎"
    if score >= 70:
        return "◎"
    if score >= 58:
        return "○"
    if score >= 43:
        return "△"
    if score >= 30:
        return "▲"
    return "×"


RATING_LABEL = {
    "◎◎": "非常に強い買い",
    "◎": "買い",
    "○": "やや買い",
    "△": "様子見",
    "▲": "やや売り",
    "×": "売り",
}

# A colored marker per rating so each holding is visually distinct at a glance
# (red = strong buy, through to black = sell).
RATING_EMOJI = {
    "◎◎": "🔴",
    "◎": "🟠",
    "○": "🟡",
    "△": "⚪",
    "▲": "🔵",
    "×": "⚫",
}


def select_reasons(signals: list[Signal], score: int, limit: int = 5) -> list[str]:
    """Pick the strongest reasons that match the overall direction (bullish if score >= 50)."""
    bullish = score >= 50
    matching = [s for s in signals if (s.points > 0) == bullish and s.points != 0]
    matching.sort(key=lambda s: abs(s.points), reverse=True)
    return [s.reason for s in matching[:limit]]


def decide_action(rating: str, profit_pct: float | None) -> str:
    if rating in ("◎◎", "◎"):
        if profit_pct is not None and profit_pct >= 15:
            return "保有継続(押し目で追加検討)"
        return "追加購入検討"
    if rating == "○":
        return "保有継続"
    if rating == "△":
        return "保有継続(様子見)"
    if rating == "▲":
        if profit_pct is not None and profit_pct > 0:
            return "一部利確検討"
        return "様子見(損切ライン注視)"
    # ×
    if profit_pct is not None and profit_pct > 0:
        return "利益確定推奨"
    return "損切推奨"


def compute_targets(
    analysis: HoldingAnalysis, rating: str
) -> tuple[float | None, float | None, float | None]:
    """Return (take_profit, stop_loss, add_price)."""
    price = analysis.current_price
    if price is None:
        return None, None, None

    if analysis.levels is not None and analysis.levels.resistance > price:
        take_profit = analysis.levels.resistance
    else:
        take_profit = price * 1.10

    if analysis.levels is not None and analysis.levels.support < price:
        stop_loss = analysis.levels.support
    else:
        stop_loss = price * 0.93

    add_price = None
    if rating in ("◎◎", "◎", "○"):
        if analysis.sma_mid is not None and analysis.sma_mid < price:
            add_price = analysis.sma_mid
        else:
            add_price = price * 0.97

    return take_profit, stop_loss, add_price


def detect_risks(analysis: HoldingAnalysis) -> list[str]:
    """Surface only material risks; an empty list means nothing noteworthy."""
    risks: list[str] = []

    if analysis.days_to_earnings is not None and 0 <= analysis.days_to_earnings <= 5:
        risks.append(f"決算まであと{analysis.days_to_earnings}日")
    if analysis.rsi is not None and analysis.rsi >= 75:
        risks.append(f"RSI{analysis.rsi:.0f}で過熱")
    if analysis.rsi is not None and analysis.rsi <= 25:
        risks.append(f"RSI{analysis.rsi:.0f}で売られすぎ")
    if analysis.bollinger is not None and analysis.bollinger >= 3:
        risks.append("バンド上限超で過熱")
    if analysis.payout_ratio is not None and analysis.payout_ratio >= 0.8:
        risks.append(f"配当性向{analysis.payout_ratio * 100:.0f}%と高水準")
    profit = analysis.profit_pct
    if profit is not None and profit <= -15:
        risks.append(f"含み損{profit:.1f}%")
    if "強い下落" in analysis.volume_price_signal:
        risks.append("出来高増加を伴う下落")

    return risks


def build_summary(analysis: HoldingAnalysis, market_sentiment: str) -> HoldingSummary:
    signals = build_signals(analysis, market_sentiment)
    raw_score = 50 + sum(s.points for s in signals)
    score = _clamp(raw_score)
    rating = rating_from_score(score)
    take_profit, stop_loss, add_price = compute_targets(analysis, rating)

    return HoldingSummary(
        symbol=analysis.holding.symbol,
        name=analysis.name,
        current_price=analysis.current_price,
        avg_cost=analysis.holding.avg_cost,
        profit_pct=analysis.profit_pct,
        score=score,
        raw_score=raw_score,
        rating=rating,
        action=decide_action(rating, analysis.profit_pct),
        take_profit=take_profit,
        stop_loss=stop_loss,
        add_price=add_price,
        reasons=select_reasons(signals, score),
        risks=detect_risks(analysis),
    )


def _price(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.0f}円"
    return f"{value:,.2f}"


DIVIDER = "━━━━━━━━━━━━"


def format_summary(summary: HoldingSummary) -> str:
    """Render a single holding summary as a compact, scannable LINE message."""
    profit = f"{summary.profit_pct:+.1f}%" if summary.profit_pct is not None else "—"
    heading = f"{summary.symbol} {summary.name}" if summary.name else summary.symbol
    marker = RATING_EMOJI[summary.rating]
    lines = [
        DIVIDER,
        f"{marker}【{heading}】",
        f"現在：{_price(summary.current_price)}",
        f"取得：{_price(summary.avg_cost)}",
        f"損益：{profit}",
        f"AI評価：{summary.rating}（{summary.score}点／{RATING_LABEL[summary.rating]}）",
        DIVIDER,
        "■判断",
        summary.action,
        f"第一目標：{_price(summary.take_profit)}",
        f"損切：{_price(summary.stop_loss)}",
    ]
    if summary.add_price is not None:
        lines.append(f"押し目買い目安：{_price(summary.add_price)}")

    lines.append(DIVIDER)
    lines.append("■判断理由")
    lines.extend(f"・{reason}" for reason in summary.reasons) if summary.reasons else lines.append(
        "・明確なシグナルなし"
    )

    if summary.risks:
        lines.append(DIVIDER)
        lines.append("■注意点")
        lines.extend(f"・{risk}" for risk in summary.risks)

    lines.append(DIVIDER)
    return "\n".join(lines)


def format_market_header(market_sentiment: str) -> str:
    return f"📊 本日の市場：{market_sentiment}"
