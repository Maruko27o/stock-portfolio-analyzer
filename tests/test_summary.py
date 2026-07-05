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
        debt_to_equity=80.0,
        current_ratio=1.6,
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


def test_score_caps_each_category():
    # Three +10 technical signals stack to 30 but are capped at 20.
    tech = [Signal(10, "t1", "technical"), Signal(10, "t2", "technical"), Signal(10, "t3", "technical")]
    assert score_from_signals(tech) == 70
    # Caps are per category: technical 20 + fundamental 18 = 88.
    mixed = tech + [Signal(30, "f", "fundamental")]
    assert score_from_signals(mixed) == 88
    # Negative side is capped symmetrically.
    bear = [Signal(-15, "t1", "technical"), Signal(-15, "t2", "technical")]
    assert score_from_signals(bear) == 30


def test_build_signals_uses_sector_thresholds():
    from stock_analyzer.summary import build_signals

    # PER 12 is cheap for the default sector (threshold 15)…
    default_sector = build_signals(_analysis(per=12.0), market_sentiment="中立")
    assert any("PER12.0で割安" in s.reason for s in default_sector)

    # …but expensive for a bank (threshold 10).
    bank = build_signals(_analysis(per=12.0, sector="Financial Services"), market_sentiment="中立")
    assert any("PER割高(セクター基準10)" in s.reason for s in bank)

    # Tech sector tolerates PER 20 (threshold 25).
    tech = build_signals(_analysis(per=20.0, sector="Technology"), market_sentiment="中立")
    assert any("PER20.0で割安(セクター基準25)" in s.reason for s in tech)


def test_build_signals_prefers_forward_per():
    from stock_analyzer.summary import build_signals

    signals = build_signals(_analysis(per=30.0, forward_per=8.0), market_sentiment="中立")
    assert any("予想PER8.0で割安" in s.reason for s in signals)


def test_build_signals_vix_regimes():
    from stock_analyzer.summary import build_signals

    risk_off = build_signals(_analysis(), market_sentiment="中立", vix=32.0)
    assert any("リスクオフ" in s.reason and s.points < 0 for s in risk_off)

    calm = build_signals(_analysis(), market_sentiment="中立", vix=13.0)
    assert any("安定" in s.reason and s.points > 0 for s in calm)


def test_build_signals_relative_strength_vs_benchmark():
    from stock_analyzer.summary import build_signals

    # Stock +10% while market +2% → own strength.
    strong = build_signals(_analysis(momentum=10.0), market_sentiment="中立", benchmark_momentum=2.0)
    assert any("市場平均より強い(+8%)" in s.reason for s in strong)

    # Stock flat while market +8% → lagging the tide.
    weak = build_signals(_analysis(momentum=0.0), market_sentiment="中立", benchmark_momentum=8.0)
    assert any("市場平均より弱い(-8%)" in s.reason for s in weak)


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


def test_decide_action_defers_selling_while_dividend_right_is_pending():
    kwargs = dict(days_to_ex_dividend=25, dividend_rate=146.0)
    assert decide_action("×", profit_pct=-8, **kwargs) == "配当権利(あと25日)まで保有→権利後に損切検討"
    assert decide_action("×", profit_pct=8, **kwargs) == "配当権利落ち(あと25日)後に利益確定推奨"
    assert decide_action("▲", profit_pct=10, **kwargs) == "配当権利落ち(あと25日)後に一部利確検討"
    # Buy-leaning advice is unchanged.
    assert decide_action("◎◎", profit_pct=5, **kwargs) == "追加購入検討"


def test_decide_action_ignores_dividend_outside_window_or_without_dividend():
    # Ex-dividend too far away (over DIVIDEND_HOLD_WINDOW_DAYS).
    assert decide_action("×", profit_pct=-8, days_to_ex_dividend=90, dividend_rate=146.0) == "損切推奨"
    # Already past (0 = today, right already secured).
    assert decide_action("×", profit_pct=-8, days_to_ex_dividend=0, dividend_rate=146.0) == "損切推奨"
    # No dividend at all.
    assert decide_action("×", profit_pct=-8, days_to_ex_dividend=10, dividend_rate=None) == "損切推奨"


def test_compute_targets_uses_levels_when_available():
    analysis = _analysis()
    take_profit, stop_loss, add_price = compute_targets(analysis, rating="◎")
    assert take_profit == 3700.0
    assert stop_loss == 3200.0
    assert add_price == 3300.0


def test_compute_targets_add_price_none_for_sell_rating():
    _, _, add_price = compute_targets(_analysis(), rating="×")
    assert add_price is None


def test_compute_targets_scales_with_atr():
    # No levels: pure ATR sizing (3 ATR target / 2 ATR stop / 1.5 ATR dip).
    analysis = _analysis(levels=None, sma_mid=None, atr=50.0)
    take_profit, stop_loss, add_price = compute_targets(analysis, rating="◎")
    assert take_profit == 3500.0 + 150.0
    assert stop_loss == 3500.0 - 100.0
    assert add_price == 3500.0 - 75.0


def test_compute_targets_replaces_levels_too_far_in_atr_terms():
    from stock_analyzer.indicators import SupportResistance

    # Support 3200 is 6 ATR away for a calm stock (ATR 50) → use 2 ATR stop instead.
    analysis = _analysis(levels=SupportResistance(support=3200.0, resistance=3700.0), atr=50.0)
    take_profit, stop_loss, _ = compute_targets(analysis, rating="◎")
    assert stop_loss == 3500.0 - 100.0
    assert take_profit == 3700.0  # resistance is within 6 ATR (200 <= 300), kept


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
    assert "■判断" in text
    assert "■判断理由" in text
    # スコア点数はバックテストで判別力なしと確認されたため表示しない
    assert "AI評価" not in text
    assert "点／" not in text
    # 各データに「見方」の一文が付く
    assert "※権利落ち日まで保有すると配当を受取" in text
    assert "※損切はこの銘柄の値動き幅(ATR)基準" in text


def test_build_summary_carries_dividend_fields_and_signal():
    from datetime import date, timedelta

    ex_date = date.today() + timedelta(days=25)
    summary = build_summary(
        _analysis(
            dividend_yield=4.24,
            dividend_rate=146.0,
            ex_dividend_date=ex_date,
            days_to_ex_dividend=25,
        ),
        market_sentiment="強気",
    )
    assert summary.dividend_yield == 4.24
    assert summary.yield_on_cost == 146.0 / 3000.0 * 100  # against avg_cost, not price
    assert summary.ex_dividend_date == ex_date
    assert summary.days_to_ex_dividend == 25

    from stock_analyzer.summary import build_signals

    signals = build_signals(
        _analysis(dividend_yield=4.24, dividend_rate=146.0, days_to_ex_dividend=25),
        market_sentiment="強気",
    )
    assert any("配当権利落ちまであと25日(利回り4.2%)" == s.reason for s in signals)


def test_yield_on_cost_none_for_watch_only_holding():
    analysis = _analysis(
        holding=Holding(symbol="1928.T", quantity=0, avg_cost=0.0), dividend_rate=146.0
    )
    assert analysis.yield_on_cost is None


def test_format_summary_always_shows_dividend_lines():
    summary = build_summary(_analysis(), market_sentiment="強気")
    text = format_summary(summary)
    assert "配当利回り：" in text
    assert "権利落ち日：データ不足" in text

    from datetime import date

    summary_with = build_summary(
        _analysis(
            dividend_yield=4.24,
            dividend_rate=146.0,
            ex_dividend_date=date(2026, 7, 30),
            days_to_ex_dividend=25,
        ),
        market_sentiment="強気",
    )
    text_with = format_summary(summary_with)
    assert "配当利回り：4.24%(取得比4.87%)" in text_with
    assert "権利落ち日：2026/7/30(あと25日)" in text_with


def test_format_ex_dividend_marks_estimated_dates():
    from datetime import date

    from stock_analyzer.summary import format_ex_dividend

    assert format_ex_dividend(date(2026, 9, 28), 85, estimated=True) == "2026/9/28(あと85日・推定)"
    assert format_ex_dividend(date(2026, 9, 28), 85, estimated=False) == "2026/9/28(あと85日)"


def test_format_as_of_only_stamps_non_current_data():
    from datetime import date

    from stock_analyzer.summary import format_as_of

    today = date(2026, 7, 5)
    assert format_as_of(None, today=today) is None
    assert format_as_of(today, today=today) is None  # same-day data needs no caveat
    assert format_as_of(date(2026, 7, 3), today=today) == "※価格は7/3(金)終値時点"


def test_format_summary_prepends_rating_emoji():
    from stock_analyzer.summary import RATING_EMOJI

    summary = build_summary(_analysis(), market_sentiment="強気")
    text = format_summary(summary)
    assert RATING_EMOJI[summary.rating] + "【" in text
