from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from stock_analyzer.analysis import HoldingAnalysis
from stock_analyzer.indicators import evaluate_macd

# Selling within this many days before the ex-dividend date forfeits the dividend,
# so sell-leaning advice is deferred until the right is secured.
DIVIDEND_HOLD_WINDOW_DAYS = 30


@dataclass
class Signal:
    """A single weighted signal contributing to the overall score, with a human-readable reason."""

    points: int
    reason: str
    category: str = "other"


# Per-category score caps. Trend indicators (SMA alignment, MACD, momentum…) all
# measure much the same thing and would otherwise stack to ±30+ in a trending
# market, drowning out fundamentals. Capping each category keeps one aspect from
# dominating the 0-100 score.
CATEGORY_CAPS = {"technical": 20, "fundamental": 18, "dividend": 6, "market": 8}

# Sector-typical valuation baselines (yfinance sector names). Banks trade at
# PER<10/PBR<0.7 in normal times while growth sectors run far higher, so a flat
# PER15/PBR1 cutoff mislabels both.
SECTOR_PER_THRESHOLD = {
    "Financial Services": 10,
    "Energy": 10,
    "Utilities": 12,
    "Basic Materials": 12,
    "Real Estate": 12,
    "Industrials": 15,
    "Consumer Cyclical": 15,
    "Consumer Defensive": 18,
    "Communication Services": 18,
    "Healthcare": 22,
    "Technology": 25,
}
DEFAULT_PER_THRESHOLD = 15
SECTOR_PBR_THRESHOLD = {
    "Financial Services": 0.7,
    "Energy": 0.8,
    "Utilities": 0.8,
    "Basic Materials": 1.0,
    "Real Estate": 1.2,
    "Industrials": 1.3,
    "Consumer Cyclical": 1.3,
    "Consumer Defensive": 1.8,
    "Communication Services": 1.8,
    "Healthcare": 2.5,
    "Technology": 3.0,
}
DEFAULT_PBR_THRESHOLD = 1.0


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
    dividend_yield: float | None = None  # % against current price
    yield_on_cost: float | None = None  # % against the user's average cost
    ex_dividend_date: date | None = None
    days_to_ex_dividend: int | None = None
    ex_dividend_estimated: bool = False
    price_score: int | None = None  # 価格由来シグナルのみのスコア(バックテスト統計の照会キー)
    backtest: dict | None = None  # 保存済みバックテスト統計(該当スコア帯の実績)
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def build_signals(
    analysis: HoldingAnalysis,
    market_sentiment: str,
    vix: float | None = None,
    benchmark_momentum: float | None = None,
) -> list[Signal]:
    """Turn the raw analysis into a list of weighted, labelled signals.

    `benchmark_momentum` is the market benchmark's 10-day rate of change, used to
    tell a stock's own strength apart from a rising tide.
    """
    signals: list[Signal] = []
    price = analysis.current_price

    # --- Technical ---
    if price is not None and analysis.sma_mid is not None:
        if price > analysis.sma_mid:
            signals.append(Signal(8, "25日線を上抜け", "technical"))
        else:
            signals.append(Signal(-8, "25日線を下回る", "technical"))

    if analysis.sma_short is not None and analysis.sma_mid is not None and analysis.sma_long is not None:
        if analysis.sma_short > analysis.sma_mid > analysis.sma_long:
            signals.append(Signal(5, "移動平均線が上昇配列", "technical"))
        elif analysis.sma_short < analysis.sma_mid < analysis.sma_long:
            signals.append(Signal(-5, "移動平均線が下降配列", "technical"))

    macd_signal = evaluate_macd(analysis.macd_result)
    if macd_signal == "ゴールデンクロス":
        signals.append(Signal(10, "MACDゴールデンクロス", "technical"))
    elif macd_signal == "デッドクロス":
        signals.append(Signal(-10, "MACDデッドクロス", "technical"))
    elif macd_signal == "上昇中":
        signals.append(Signal(4, "MACD上昇中", "technical"))
    elif macd_signal == "下降中":
        signals.append(Signal(-4, "MACD下降中", "technical"))

    if analysis.rsi is not None:
        if analysis.rsi <= 30:
            signals.append(Signal(8, f"RSI{analysis.rsi:.0f}で売られすぎ(反発期待)", "technical"))
        elif analysis.rsi >= 70:
            signals.append(Signal(-8, f"RSI{analysis.rsi:.0f}で買われすぎ", "technical"))

    if "強い上昇" in analysis.volume_price_signal:
        signals.append(Signal(6, "出来高増加を伴う上昇", "technical"))
    elif "勢い弱い" in analysis.volume_price_signal:
        signals.append(Signal(-2, "上昇も出来高が細る", "technical"))
    elif "強い下落" in analysis.volume_price_signal:
        signals.append(Signal(-6, "出来高増加を伴う下落", "technical"))
    elif "下げ渋り" in analysis.volume_price_signal:
        signals.append(Signal(2, "下落だが出来高は減少", "technical"))

    if analysis.levels is not None and price is not None:
        if price >= analysis.levels.resistance:
            signals.append(Signal(5, "レジスタンスを突破", "technical"))
        elif price <= analysis.levels.support:
            signals.append(Signal(-5, "サポートを割れ", "technical"))

    if analysis.bollinger is not None:
        if analysis.bollinger >= 2:
            signals.append(Signal(-3, "ボリンジャーバンド上限で過熱", "technical"))
        elif analysis.bollinger <= -2:
            signals.append(Signal(3, "ボリンジャーバンド下限で反発期待", "technical"))

    if analysis.momentum is not None:
        if analysis.momentum >= 10:
            signals.append(Signal(6, f"直近10日で+{analysis.momentum:.0f}%の強い上昇", "technical"))
        elif analysis.momentum >= 3:
            signals.append(Signal(3, f"直近10日で+{analysis.momentum:.0f}%上昇", "technical"))
        elif analysis.momentum <= -10:
            signals.append(Signal(-6, f"直近10日で{analysis.momentum:.0f}%下落", "technical"))
        elif analysis.momentum <= -3:
            signals.append(Signal(-3, "直近10日で下落", "technical"))

    # Own strength vs the market: a rise that just tracks the index is tide, not skill.
    if analysis.momentum is not None and benchmark_momentum is not None:
        relative = analysis.momentum - benchmark_momentum
        if relative >= 5:
            signals.append(Signal(4, f"市場平均より強い(+{relative:.0f}%)", "technical"))
        elif relative <= -5:
            signals.append(Signal(-4, f"市場平均より弱い({relative:.0f}%)", "technical"))

    # --- Fundamental ---
    per_threshold = SECTOR_PER_THRESHOLD.get(analysis.sector, DEFAULT_PER_THRESHOLD)
    per_value = analysis.forward_per if analysis.forward_per is not None else analysis.per
    per_label = "予想PER" if analysis.forward_per is not None else "PER"
    if per_value is not None:
        if per_value <= 0:
            signals.append(Signal(-4, f"{per_label}マイナス(赤字)", "fundamental"))
        elif per_value <= per_threshold:
            signals.append(
                Signal(6, f"{per_label}{per_value:.1f}で割安(セクター基準{per_threshold})", "fundamental")
            )
        else:
            signals.append(Signal(-3, f"{per_label}割高(セクター基準{per_threshold})", "fundamental"))

    pbr_threshold = SECTOR_PBR_THRESHOLD.get(analysis.sector, DEFAULT_PBR_THRESHOLD)
    if analysis.pbr is not None:
        if analysis.pbr <= pbr_threshold:
            signals.append(
                Signal(5, f"PBR{analysis.pbr:.1f}で割安(セクター基準{pbr_threshold})", "fundamental")
            )
        else:
            signals.append(Signal(-2, f"PBR割高(セクター基準{pbr_threshold})", "fundamental"))

    if analysis.roe is not None:
        signals.append(
            Signal(6, "ROE良好", "fundamental")
            if analysis.roe >= 0.08
            else Signal(-2, "ROEが低い", "fundamental")
        )
    if analysis.roa is not None:
        signals.append(
            Signal(5, "ROA良好", "fundamental")
            if analysis.roa >= 0.05
            else Signal(-2, "ROAが低い", "fundamental")
        )
    if analysis.revenue_growth is not None:
        signals.append(
            Signal(4, "増収", "fundamental")
            if analysis.revenue_growth > 0
            else Signal(-4, "減収", "fundamental")
        )
    if analysis.earnings_growth is not None:
        signals.append(
            Signal(5, "増益", "fundamental")
            if analysis.earnings_growth > 0
            else Signal(-5, "減益", "fundamental")
        )
    if analysis.debt_to_equity is not None:
        if analysis.debt_to_equity <= 100:
            signals.append(Signal(3, "財務健全(低負債)", "fundamental"))
        elif analysis.debt_to_equity >= 200:
            signals.append(Signal(-3, "負債が多い", "fundamental"))
    if analysis.current_ratio is not None:
        if analysis.current_ratio >= 1.5:
            signals.append(Signal(2, "短期の支払い余力あり", "fundamental"))
        elif analysis.current_ratio < 1.0:
            signals.append(Signal(-3, "短期の支払い能力に注意", "fundamental"))

    # --- Dividend ---
    if analysis.dividend_yield is not None and analysis.dividend_yield >= 3.0:
        signals.append(Signal(3, f"高配当利回り{analysis.dividend_yield:.1f}%", "dividend"))
    if (
        analysis.days_to_ex_dividend is not None
        and 1 <= analysis.days_to_ex_dividend <= DIVIDEND_HOLD_WINDOW_DAYS
        and analysis.dividend_rate
    ):
        label = f"配当権利落ちまであと{analysis.days_to_ex_dividend}日"
        if analysis.dividend_yield is not None:
            label += f"(利回り{analysis.dividend_yield:.1f}%)"
        signals.append(Signal(4, label, "dividend"))

    # --- Market ---
    if market_sentiment == "強気":
        signals.append(Signal(5, "市場全体が上昇基調", "market"))
    elif market_sentiment == "弱気":
        signals.append(Signal(-5, "市場全体が下落基調", "market"))

    if vix is not None:
        if vix >= 30:
            signals.append(Signal(-8, f"VIX{vix:.0f}でリスクオフ(買い抑制)", "market"))
        elif vix >= 25:
            signals.append(Signal(-4, f"VIX{vix:.0f}で警戒水準", "market"))
        elif vix <= 15:
            signals.append(Signal(2, f"VIX{vix:.0f}で市場は安定", "market"))

    return signals


def _capped_total(signals: list[Signal]) -> int:
    """Sum signal points with each category clamped to its cap (uncategorized: uncapped)."""
    per_category: dict[str, int] = {}
    for signal in signals:
        per_category[signal.category] = per_category.get(signal.category, 0) + signal.points

    total = 0
    for category, points in per_category.items():
        cap = CATEGORY_CAPS.get(category)
        total += max(-cap, min(cap, points)) if cap else points
    return total


def score_from_signals(signals: list[Signal]) -> int:
    return _clamp(50 + _capped_total(signals))


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


def decide_action(
    rating: str,
    profit_pct: float | None,
    days_to_ex_dividend: int | None = None,
    dividend_rate: float | None = None,
) -> str:
    # Selling before the ex-dividend date forfeits the dividend, so while the
    # right is still pending, sell-leaning advice waits until it is secured.
    dividend_pending = (
        days_to_ex_dividend is not None
        and 1 <= days_to_ex_dividend <= DIVIDEND_HOLD_WINDOW_DAYS
        and bool(dividend_rate)
    )

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
            if dividend_pending:
                return f"配当権利落ち(あと{days_to_ex_dividend}日)後に一部利確検討"
            return "一部利確検討"
        return "様子見(損切ライン注視)"
    # ×
    if profit_pct is not None and profit_pct > 0:
        if dividend_pending:
            return f"配当権利落ち(あと{days_to_ex_dividend}日)後に利益確定推奨"
        return "利益確定推奨"
    if dividend_pending:
        return f"配当権利(あと{days_to_ex_dividend}日)まで保有→権利後に損切検討"
    return "損切推奨"


def compute_targets(
    analysis: HoldingAnalysis, rating: str
) -> tuple[float | None, float | None, float | None]:
    """Return (take_profit, stop_loss, add_price).

    Distances are sized in ATR units (each stock's own daily range) so a calm
    large-cap and a volatile small-cap get appropriately different lines; the
    flat ±% values remain only as a fallback when ATR is unavailable.
    Support/resistance levels are still preferred, but a level absurdly far
    away in ATR terms is replaced by the ATR-based line.
    """
    price = analysis.current_price
    if price is None:
        return None, None, None
    atr = analysis.atr

    take_profit = None
    if analysis.levels is not None and analysis.levels.resistance > price:
        take_profit = analysis.levels.resistance
        if atr and take_profit > price + 6 * atr:
            take_profit = price + 3 * atr
    if take_profit is None:
        take_profit = price + 3 * atr if atr else price * 1.10

    stop_loss = None
    if analysis.levels is not None and analysis.levels.support < price:
        stop_loss = analysis.levels.support
        if atr and stop_loss < price - 4 * atr:
            stop_loss = price - 2 * atr
    if stop_loss is None:
        stop_loss = price - 2 * atr if atr else price * 0.93

    add_price = None
    if rating in ("◎◎", "◎", "○"):
        if analysis.sma_mid is not None and analysis.sma_mid < price:
            add_price = analysis.sma_mid
        else:
            add_price = price - 1.5 * atr if atr else price * 0.97

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
    if analysis.current_ratio is not None and analysis.current_ratio < 1.0:
        risks.append("流動比率1.0未満(短期支払い能力に注意)")

    return risks


def build_summary(
    analysis: HoldingAnalysis,
    market_sentiment: str,
    vix: float | None = None,
    benchmark_momentum: float | None = None,
) -> HoldingSummary:
    signals = build_signals(analysis, market_sentiment, vix, benchmark_momentum)
    raw_score = 50 + _capped_total(signals)
    score = _clamp(raw_score)
    # バックテストは価格から算出可能なシグナルだけで検証しているため、
    # 実績統計の照会には同じ範囲で計算したスコアを使う。
    price_signals = [s for s in signals if s.category in ("technical", "dividend", "market")]
    price_score = _clamp(50 + _capped_total(price_signals))
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
        action=decide_action(
            rating, analysis.profit_pct, analysis.days_to_ex_dividend, analysis.dividend_rate
        ),
        take_profit=take_profit,
        stop_loss=stop_loss,
        add_price=add_price,
        dividend_yield=analysis.dividend_yield,
        yield_on_cost=analysis.yield_on_cost,
        ex_dividend_date=analysis.ex_dividend_date,
        days_to_ex_dividend=analysis.days_to_ex_dividend,
        ex_dividend_estimated=analysis.ex_dividend_estimated,
        price_score=price_score,
        reasons=select_reasons(signals, score),
        risks=detect_risks(analysis),
    )


def _price(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.0f}円"
    return f"{value:,.2f}"


def format_dividend_yield(dividend_yield: float | None, yield_on_cost: float | None) -> str:
    """Render '4.24%(取得比4.87%)' — current yield plus the yield on the user's own cost."""
    if dividend_yield is None and yield_on_cost is None:
        return "—"
    text = f"{dividend_yield:.2f}%" if dividend_yield is not None else "—"
    if yield_on_cost is not None:
        text += f"(取得比{yield_on_cost:.2f}%)"
    return text


def format_ex_dividend(
    ex_dividend_date: date | None,
    days_to_ex_dividend: int | None,
    estimated: bool = False,
) -> str:
    if ex_dividend_date is None:
        return "データ不足"
    text = f"{ex_dividend_date.year}/{ex_dividend_date.month}/{ex_dividend_date.day}"
    mark = "・推定" if estimated else ""
    if days_to_ex_dividend is None:
        return f"{text}(推定)" if estimated else text
    if days_to_ex_dividend > 0:
        return f"{text}(あと{days_to_ex_dividend}日{mark})"
    if days_to_ex_dividend == 0:
        return f"{text}(本日{mark})"
    return f"{text}(通過)"


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
        f"配当利回り：{format_dividend_yield(summary.dividend_yield, summary.yield_on_cost)}",
        f"権利落ち日：{format_ex_dividend(summary.ex_dividend_date, summary.days_to_ex_dividend, summary.ex_dividend_estimated)}",
        f"AI評価：{summary.rating}（{summary.score}点／{RATING_LABEL[summary.rating]}）",
        DIVIDER,
        "■判断",
        summary.action,
        f"第一目標：{_price(summary.take_profit)}",
        f"損切：{_price(summary.stop_loss)}",
    ]
    if summary.add_price is not None:
        lines.append(f"押し目買い目安：{_price(summary.add_price)}")

    if summary.backtest:
        from stock_analyzer.backtest_stats import format_backtest_lines

        lines.append(DIVIDER)
        lines.append("■バックテスト実績")
        lines.extend(format_backtest_lines(summary.backtest))

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


def format_as_of(as_of: date | None, today: date | None = None) -> str | None:
    """Render the "prices as of" stamp; None when there is nothing to show.

    Fresh same-day data needs no caveat, so a stamp is returned only when the
    latest available price is from an earlier day (weekend/holiday runs, stale
    data source) — exactly when the reader would otherwise be misled.
    """
    if as_of is None:
        return None
    if today is None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    if as_of == today:
        return None
    weekday = "月火水木金土日"[as_of.weekday()]
    return f"※価格は{as_of.month}/{as_of.day}({weekday})終値時点"
