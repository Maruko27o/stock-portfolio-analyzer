from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from stock_analyzer import config, valuation
from stock_analyzer.analysis import HoldingAnalysis
from stock_analyzer.config import (  # noqa: F401  (後方互換の再エクスポート)
    CATEGORY_CAPS,
    DEFAULT_PBR_THRESHOLD,
    DEFAULT_PER_THRESHOLD,
    SECTOR_PBR_THRESHOLD,
    SECTOR_PER_THRESHOLD,
)
from stock_analyzer import model_store
from stock_analyzer.indicators import evaluate_macd
from stock_analyzer.valuation import analyst_upside_pct, discount_pct

# アナリスト合意を「現実性チェック」に使う最小カバレッジ。
MIN_ANALYSTS_FOR_VALUATION = 3

# Selling within this many days before the ex-dividend date forfeits the dividend,
# so sell-leaning advice is deferred until the right is secured.
DIVIDEND_HOLD_WINDOW_DAYS = 30


@dataclass
class Signal:
    """A single weighted signal contributing to the overall score, with a human-readable reason."""

    points: int
    reason: str
    category: str = "other"


# カテゴリ上限・セクター別の割安基準は config.py へ移設した(上でインポート)。
# 後方互換のため名前はこのモジュールからも引き続き参照できる。


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
    strategies_active: list = field(default_factory=list)  # 成立中の戦略タイプ
    strategy_stats: dict | None = None  # 主戦略の検証期間実績(保存済み統計から)
    horizons: list = field(default_factory=list)  # 保有期間別のスコア帯実績
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    subscores: dict = field(default_factory=dict)  # [カテゴリ4]カテゴリ別サブスコア(監査用)


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
    w = model_store.technical_weights()  # 重みの単一出所(backtestと共有)

    # --- Technical ---
    if price is not None and analysis.sma_mid is not None:
        if price > analysis.sma_mid:
            signals.append(Signal(w["sma25"], "25日線を上抜け", "technical"))
        else:
            signals.append(Signal(-w["sma25"], "25日線を下回る", "technical"))

    if analysis.sma_short is not None and analysis.sma_mid is not None and analysis.sma_long is not None:
        if analysis.sma_short > analysis.sma_mid > analysis.sma_long:
            signals.append(Signal(w["ma_align"], "移動平均線が上昇配列", "technical"))
        elif analysis.sma_short < analysis.sma_mid < analysis.sma_long:
            signals.append(Signal(-w["ma_align"], "移動平均線が下降配列", "technical"))

    macd_signal = evaluate_macd(analysis.macd_result)
    if macd_signal == "ゴールデンクロス":
        signals.append(Signal(w["macd_cross"], "MACDゴールデンクロス", "technical"))
    elif macd_signal == "デッドクロス":
        signals.append(Signal(-w["macd_cross"], "MACDデッドクロス", "technical"))
    elif macd_signal == "上昇中":
        signals.append(Signal(w["macd_trend"], "MACD上昇中", "technical"))
    elif macd_signal == "下降中":
        signals.append(Signal(-w["macd_trend"], "MACD下降中", "technical"))

    if analysis.rsi is not None:
        if analysis.rsi <= 30:
            signals.append(Signal(w["rsi_extreme"], f"RSI{analysis.rsi:.0f}で売られすぎ(反発期待)", "technical"))
        elif analysis.rsi >= 70:
            signals.append(Signal(-w["rsi_extreme"], f"RSI{analysis.rsi:.0f}で買われすぎ", "technical"))

    if "強い上昇" in analysis.volume_price_signal:
        signals.append(Signal(w["vol_strong_up"], "出来高増加を伴う上昇", "technical"))
    elif "勢い弱い" in analysis.volume_price_signal:
        signals.append(Signal(-w["vol_weak_up"], "上昇も出来高が細る", "technical"))
    elif "強い下落" in analysis.volume_price_signal:
        signals.append(Signal(-w["vol_strong_down"], "出来高増加を伴う下落", "technical"))
    elif "下げ渋り" in analysis.volume_price_signal:
        signals.append(Signal(w["vol_dip"], "下落だが出来高は減少", "technical"))

    if analysis.levels is not None and price is not None:
        if price >= analysis.levels.resistance:
            signals.append(Signal(w["sr_break"], "レジスタンスを突破", "technical"))
        elif price <= analysis.levels.support:
            signals.append(Signal(-w["sr_break"], "サポートを割れ", "technical"))

    if analysis.bollinger is not None:
        if analysis.bollinger >= 2:
            signals.append(Signal(-w["bb"], "ボリンジャーバンド上限で過熱", "technical"))
        elif analysis.bollinger <= -2:
            signals.append(Signal(w["bb"], "ボリンジャーバンド下限で反発期待", "technical"))

    if analysis.momentum is not None:
        if analysis.momentum >= 10:
            signals.append(Signal(w["mom_strong"], f"直近10日で+{analysis.momentum:.0f}%の強い上昇", "technical"))
        elif analysis.momentum >= 3:
            signals.append(Signal(w["mom_mild"], f"直近10日で+{analysis.momentum:.0f}%上昇", "technical"))
        elif analysis.momentum <= -10:
            signals.append(Signal(-w["mom_strong"], f"直近10日で{analysis.momentum:.0f}%下落", "technical"))
        elif analysis.momentum <= -3:
            signals.append(Signal(-w["mom_mild"], "直近10日で下落", "technical"))

    # Own strength vs the market: a rise that just tracks the index is tide, not skill.
    if analysis.momentum is not None and benchmark_momentum is not None:
        relative = analysis.momentum - benchmark_momentum
        if relative >= 5:
            signals.append(Signal(w["rel"], f"市場平均より強い(+{relative:.0f}%)", "technical"))
        elif relative <= -5:
            signals.append(Signal(-w["rel"], f"市場平均より弱い({relative:.0f}%)", "technical"))

    # --- Fundamental ---
    per_threshold = SECTOR_PER_THRESHOLD.get(analysis.sector, DEFAULT_PER_THRESHOLD)
    per_value = analysis.forward_per if analysis.forward_per is not None else analysis.per
    per_label = "予想PER" if analysis.forward_per is not None else "PER"
    if per_value is not None:
        if per_value <= 0:
            signals.append(Signal(-4, f"{per_label}マイナス(赤字)", "fundamental"))
        elif not valuation.per_is_plausible(per_value, analysis.sector):
            # [カテゴリ14] 同業種の目安から極端に外れるPERは異常値。割安判定に使わない
            # (スコアへ加点しない)。要確認としてリスク側で明示する。
            pass
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
    dw = model_store.DIVIDEND_WEIGHTS
    if analysis.dividend_yield is not None and analysis.dividend_yield >= 3.0:
        signals.append(Signal(dw["high_yield"], f"高配当利回り{analysis.dividend_yield:.1f}%", "dividend"))
    if (
        analysis.days_to_ex_dividend is not None
        and 1 <= analysis.days_to_ex_dividend <= DIVIDEND_HOLD_WINDOW_DAYS
        and analysis.dividend_rate
    ):
        label = f"配当権利落ちまであと{analysis.days_to_ex_dividend}日"
        if analysis.dividend_yield is not None:
            label += f"(利回り{analysis.dividend_yield:.1f}%)"
        signals.append(Signal(dw["ex_div_near"], label, "dividend"))

    # --- Market ---
    mw = model_store.MARKET_WEIGHTS
    if market_sentiment == "強気":
        signals.append(Signal(mw["sentiment"], "市場全体が上昇基調", "market"))
    elif market_sentiment == "弱気":
        signals.append(Signal(-mw["sentiment"], "市場全体が下落基調", "market"))

    if vix is not None:
        if vix >= 30:
            signals.append(Signal(-mw["vix_high"], f"VIX{vix:.0f}でリスクオフ(買い抑制)", "market"))
        elif vix >= 25:
            signals.append(Signal(-mw["vix_warn"], f"VIX{vix:.0f}で警戒水準", "market"))
        elif vix <= 15:
            signals.append(Signal(mw["vix_calm"], f"VIX{vix:.0f}で市場は安定", "market"))

    # --- Valuation reality-check(アナリスト合意・株価位置で「割安に見えるだけ」を補正) ---
    signals.extend(_valuation_signals(analysis))

    return signals


def _price_position(analysis: HoldingAnalysis) -> float | None:
    """52週レンジ内の位置(0=安値、1=高値)。算出不能なら None。"""
    hi, lo, cur = analysis.period_high, analysis.period_low, analysis.current_price
    if hi is None or lo is None or cur is None or hi <= lo:
        return None
    return (cur - lo) / (hi - lo)


def _valuation_signals(analysis: HoldingAnalysis) -> list["Signal"]:
    """割安の「質」をアナリスト合意と株価位置で検証するシグナル(category=valuation)。

    PBRやPERが低いだけ、あるいは上昇して高値圏に来た銘柄を機械的に「強い買い」に
    しないための現実性チェック。アナリストは減益ガイダンスや政策リスクを織り込むため、
    「社内モデルは割安と言うがアナリストは上値を見ていない」= バリュートラップの警戒に使う。
    """
    signals: list[Signal] = []
    upside = analyst_upside_pct(analysis)
    n = analysis.num_analysts or 0

    if upside is not None and n >= MIN_ANALYSTS_FOR_VALUATION:
        if upside < 0:
            signals.append(Signal(-8, "現在値がアナリスト目標を超過(上値限定)", "valuation"))
        elif upside < 8:
            signals.append(Signal(-6, f"アナリスト上値わずか(+{upside:.0f}%)", "valuation"))
        elif upside < 15:
            pass  # ほどほど。加点も減点もしない
        elif upside < 25:
            signals.append(Signal(3, f"アナリスト上値余地(+{upside:.0f}%)", "valuation"))
        else:
            signals.append(Signal(6, f"アナリスト上値大(+{upside:.0f}%)", "valuation"))

        # バリュートラップ警戒: 社内は「かなり割安」だがアナリストは上値を見ていない
        disc = discount_pct(analysis)
        if disc is not None and disc <= -15 and upside < 10:
            signals.append(
                Signal(-6, "割安に見えるがアナリストは慎重(バリュートラップ警戒)", "valuation")
            )

    rec = analysis.recommendation_mean
    if rec is not None and n >= MIN_ANALYSTS_FOR_VALUATION:
        if rec <= 2.0:
            signals.append(Signal(2, "アナリスト推奨が強気", "valuation"))
        elif rec >= 3.0:
            signals.append(Signal(-4, "アナリスト推奨が慎重", "valuation"))

    pos = _price_position(analysis)
    if pos is not None:
        if pos >= 0.75:
            signals.append(Signal(-7, "52週高値圏(値ごろ感は乏しく押し目待ち)", "valuation"))
        elif pos <= 0.35:
            signals.append(Signal(2, "52週安値圏(値ごろ)", "valuation"))
            # 安値圏でも中期トレンドの下なら底打ち未確認=落ちるナイフに注意
            if analysis.sma_long is not None and analysis.current_price is not None and (
                analysis.current_price < analysis.sma_long
            ):
                signals.append(Signal(-3, "下降トレンドの安値圏(底打ち未確認)", "valuation"))

    return signals


def category_subscores(signals: list[Signal]) -> dict[str, int]:
    """カテゴリ別の(上限クリップ後)寄与点を返す [カテゴリ4:安定性の監査用]。

    どのサブスコア(テクニカル/ファンダ/需給/市場…)がスコアを動かしたかを
    後から突き合わせられるよう、内部監査ログのキーとして保持する。
    """
    per_category: dict[str, int] = {}
    for signal in signals:
        per_category[signal.category] = per_category.get(signal.category, 0) + signal.points
    out: dict[str, int] = {}
    for category, points in per_category.items():
        cap = CATEGORY_CAPS.get(category)
        out[category] = max(-cap, min(cap, points)) if cap else points
    return out


def _capped_total(signals: list[Signal]) -> int:
    """Sum signal points with each category clamped to its cap (uncategorized: uncapped)."""
    return sum(category_subscores(signals).values())


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


def detect_strategies(analysis: HoldingAnalysis) -> list[str]:
    """成立している戦略タイプを返す(research.strategy_frameと同一定義)。

    優先順: ブレイクアウト > 順張り > 逆張り > レンジ。
    """
    active: list[str] = []
    price = analysis.current_price

    breakout = (
        price is not None
        and analysis.levels is not None
        and price >= analysis.levels.resistance
        and "強い上昇" in analysis.volume_price_signal
    )
    trend = (
        price is not None
        and analysis.sma_short is not None
        and analysis.sma_mid is not None
        and analysis.sma_long is not None
        and price > analysis.sma_mid
        and analysis.sma_short > analysis.sma_mid > analysis.sma_long
        and analysis.macd_result is not None
        and analysis.macd_result.macd > analysis.macd_result.signal
    )
    contrarian = (analysis.rsi is not None and analysis.rsi <= 30) or (
        analysis.bollinger is not None and analysis.bollinger <= -2
    )
    sma_flat = (
        analysis.sma_mid is not None
        and analysis.sma_mid_prev10
        and abs(analysis.sma_mid / analysis.sma_mid_prev10 - 1) < 0.01
    )
    range_bound = (
        sma_flat
        and analysis.bollinger is not None
        and abs(analysis.bollinger) < 1
        and not trend
        and not breakout
    )

    if breakout:
        active.append("ブレイクアウト")
    if trend:
        active.append("順張り")
    if contrarian:
        active.append("逆張り")
    if range_bound:
        active.append("レンジ")
    return active


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
    """明文化したリスク表示条件に該当する項目だけを返す [カテゴリ7]。

    表示条件(config で一元管理):
    - RSI >= RISK_RSI_OVERBOUGHT(70) で過熱 / RSI <= RISK_RSI_OVERSOLD(30) で売られすぎ
    - 配当性向 >= RISK_PAYOUT_RATIO_MAX(200%) で減配リスク大(80%以上でも高水準として表示)
    - 流動比率 < RISK_CURRENT_RATIO_MIN(1.2) で短期支払い能力に注意
    - 決算5日以内 / バンド上限超 / 含み損-15%超 / 出来高増を伴う下落
    空リストなら表示しない(該当時は必ず表示、非該当時は省略。挙動はテストで担保)。
    """
    risks: list[str] = []

    if analysis.days_to_earnings is not None and 0 <= analysis.days_to_earnings <= 5:
        risks.append(f"決算まであと{analysis.days_to_earnings}日")
    if analysis.rsi is not None and analysis.rsi >= config.RISK_RSI_OVERBOUGHT:
        risks.append(f"RSI{analysis.rsi:.0f}で過熱(買われすぎ)")
    if analysis.rsi is not None and analysis.rsi <= config.RISK_RSI_OVERSOLD:
        risks.append(f"RSI{analysis.rsi:.0f}で売られすぎ")
    if analysis.bollinger is not None and analysis.bollinger >= 3:
        risks.append("バンド上限超で過熱")
    if analysis.payout_ratio is not None and analysis.payout_ratio >= config.RISK_PAYOUT_RATIO_MAX:
        risks.append(f"配当性向{analysis.payout_ratio * 100:.0f}%(200%超・減配リスク大)")
    elif analysis.payout_ratio is not None and analysis.payout_ratio >= 0.8:
        risks.append(f"配当性向{analysis.payout_ratio * 100:.0f}%と高水準")
    profit = analysis.profit_pct
    if profit is not None and profit <= -15:
        risks.append(f"含み損{profit:.1f}%")
    if "強い下落" in analysis.volume_price_signal:
        risks.append("出来高増加を伴う下落")
    if analysis.current_ratio is not None and analysis.current_ratio < config.RISK_CURRENT_RATIO_MIN:
        risks.append(
            f"流動比率{analysis.current_ratio:.2f}"
            f"(<{config.RISK_CURRENT_RATIO_MIN:.1f}・短期支払い能力に注意)"
        )
    # [カテゴリ14] 正のPERが同業種目安から極端に外れる=異常値。割安根拠から除外済みである旨を明示。
    per_value = analysis.forward_per if analysis.forward_per is not None else analysis.per
    if per_value is not None and per_value > 0 and not valuation.per_is_plausible(per_value, analysis.sector):
        risks.append(f"PER{per_value:.1f}は異常値の疑い(算出不可・要確認/割安判定から除外)")

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
        strategies_active=detect_strategies(analysis),
        reasons=select_reasons(signals, score),
        risks=detect_risks(analysis),
        subscores=category_subscores(signals),
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
    """Render a single holding summary as a compact, scannable LINE message.

    バックテストで判別力が無いと確認された表示(AIスコア点数・スコア帯実績・
    期間別4行)は出さず、根拠のある情報だけを「※見方」の一文付きで出す。
    """
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
        "※権利落ち日まで保有すると配当を受取。売却は権利後が基本",
        DIVIDER,
        "■判断",
        summary.action,
        f"損切：{_price(summary.stop_loss)}／目標：{_price(summary.take_profit)}",
    ]
    if summary.add_price is not None:
        lines.append(f"押し目買い目安：{_price(summary.add_price)}")
    lines.append("※損切はこの銘柄の値動き幅(ATR)基準。終値で割れたら売却を検討")

    if summary.strategy_stats:
        st = summary.strategy_stats
        scope = f"({st['regime']}相場)" if st.get("regime") else ""
        lines.append(DIVIDER)
        lines.append(f"■戦略シグナル：{st['strategy']}{scope}")
        lines.append(
            f"検証勝率：{st['win_rate']:.1f}%／期待値：{st['expectancy']:+.1f}%／{st['count']:,}件"
        )
        lines.append("※銘柄の優劣でなく「買い時の型」の検知。下落・横ばい相場で特に有効")

    if summary.horizons and summary.current_price is not None:
        price = summary.current_price
        detail = summary.horizons[-1]
        if "p25" in detail:
            rng = lambda lo, hi: (  # noqa: E731
                f"{_price(price * (1 + detail[lo] / 100))}〜{_price(price * (1 + detail[hi] / 100))}"
            )
            lines.append(DIVIDER)
            lines.append(f"■{detail['days']}日後の見通し(信頼度{detail['stars']})")
            lines.append(
                f"期待価格：{_price(price * (1 + detail['expectancy'] / 100))}"
                f"({detail['expectancy']:+.1f}%／勝率{detail['win_rate']:.0f}%)"
            )
            lines.append(f"50%レンジ：{rng('p25', 'p75')}")
            lines.append(f"80%レンジ：{rng('p10', 'p90')}")
            lines.append(
                f"+5%以上：{detail['prob_up_5']:.0f}%／-5%以下：{detail['prob_down_5']:.0f}%"
            )
            lines.append("※期待値の1点よりブレ幅(レンジ)を重視。レンジ外もあり得る")

    lines.append(DIVIDER)
    lines.append("■判断理由")
    reasons = summary.reasons[:3]
    lines.extend(f"・{reason}" for reason in reasons) if reasons else lines.append(
        "・明確なシグナルなし"
    )

    if summary.risks:
        lines.append(DIVIDER)
        lines.append("■注意点")
        lines.extend(f"・{risk}" for risk in summary.risks)
        lines.append("※該当した銘柄だけに表示。売買前に必ず確認")

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
