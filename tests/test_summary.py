from stock_analyzer.analysis import HoldingAnalysis
from stock_analyzer.indicators import MACDResult, SupportResistance
from stock_analyzer.portfolio import Holding
from stock_analyzer.summary import (
    Signal,
    build_summary,
    compute_targets,
    decide_action,
    detect_risks,
    format_summary,
    rating_from_score,
    score_from_signals,
    select_reasons,
)


def _analysis(**overrides) -> HoldingAnalysis:
    defaults = dict(
        holding=Holding(symbol="7203.T", quantity=100, avg_cost=3000.0),
        name="Toyota Motor Corporation",
        current_price=3500.0,
        sma_short=3450.0,
        sma_mid=3300.0,
        sma_long=3100.0,
        rsi=58.0,
        momentum=4.0,
        macd_result=None,
        bollinger=0.5,
        volume_signal="増加",
        volume_trend_ratio=1.3,
        volume_price_signal="価格上昇×出来高増加(強い上昇)",
        levels=SupportResistance(support=3200.0, resistance=3700.0),
        period_high=3800.0,
        period_low=2900.0,
        per=12.0,
        pbr=0.9,
        dividend_yield=0.02,
        roe=0.12,
        roa=0.07,
        eps=250.0,
        bps=3200.0,
        revenue_growth=0.08,
        earnings_growth=0.15,
        payout_ratio=0.3,
        sector="Consumer Cyclical",
        industry="Auto Manufacturers",
        next_earnings=None,
        days_to_earnings=None,
    )
    defaults.update(overrides)
    return HoldingAnalysis(**defaults)


def test_rating_from_score_boundaries():
    assert rating_from_score(90) == "◎◎"
    assert rating_from_score(70) == "◎"
    assert rating_from_score(58) == "○"
    assert rating_from_score(43) == "△"
    assert rating_from_score(30) == "▲"
    assert rating_from_score(10) == "×"


def test_score_from_signals_clamps_and_sums():
    assert score_from_signals([Signal(10, "a"), Signal(-4, "b")]) == 56
    assert score_from_signals([Signal(100, "big")]) == 100
    assert score_from_signals([Signal(-100, "big")]) == 0


def test_select_reasons_picks_matching_direction_by_magnitude():
    signals = [Signal(10, "強い買い"), Signal(4, "弱い買い"), Signal(-3, "弱い売り")]
    reasons = select_reasons(signals, score=70, limit=5)
    assert reasons == ["強い買い", "弱い買い"]


def test_select_reasons_bearish_direction():
    signals = [Signal(-10, "強い売り"), Signal(3, "弱い買い")]
    reasons = select_reasons(signals, score=30)
    assert reasons == ["強い売り"]


def test_decide_action_varies_by_rating_and_profit():
    assert decide_action("◎◎", profit_pct=5) == "追加購入検討"
    assert decide_action("◎", profit_pct=20) == "保有継続(押し目で追加検討)"
    assert decide_action("○", profit_pct=None) == "保有継続"
    assert decide_action("▲", profit_pct=10) == "一部利確検討"
    assert decide_action("×", profit_pct=8) == "利益確定推奨"
    assert decide_action("×", profit_pct=-8) == "損切推奨"


def test_compute_targets_uses_levels_when_available():
    analysis = _analysis()
    take_profit, stop_loss, add_price = compute_targets(analysis, rating="◎")
    assert take_profit == 3700.0
    assert stop_loss == 3200.0
    assert add_price == 3300.0


def test_compute_targets_add_price_none_for_sell_rating():
    _, _, add_price = compute_targets(_analysis(), rating="×")
    assert add_price is None


def test_detect_risks_flags_earnings_and_overheating():
    analysis = _analysis(days_to_earnings=3, rsi=78.0)
    risks = detect_risks(analysis)
    assert any("決算まであと3日" in r for r in risks)
    assert any("RSI78" in r for r in risks)


def test_detect_risks_empty_when_calm():
    assert detect_risks(_analysis()) == []


def test_build_summary_bullish_case():
    summary = build_summary(_analysis(), market_sentiment="強気")
    assert summary.score > 50
    assert summary.rating in ("◎◎", "◎", "○")
    assert summary.profit_pct == (3500.0 - 3000.0) / 3000.0 * 100
    assert len(summary.reasons) >= 1


def test_format_summary_contains_key_sections():
    summary = build_summary(_analysis(macd_result=MACDResult(1, 0.5, 0.5, 0.4, 0.5)), market_sentiment="強気")
    text = format_summary(summary)
    assert "【7203.T Toyota Motor Corporation】" in text
    assert "AI評価" in text
    assert "■判断" in text
    assert "■判断理由" in text


def test_format_summary_prepends_rating_emoji():
    from stock_analyzer.summary import RATING_EMOJI

    summary = build_summary(_analysis(), market_sentiment="強気")
    text = format_summary(summary)
    assert RATING_EMOJI[summary.rating] + "【" in text
