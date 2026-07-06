from __future__ import annotations

from stock_analyzer.analysis import HoldingAnalysis
from stock_analyzer.indicators import SupportResistance
from stock_analyzer.horizon_model import (
    LONG_TERM_MAX_STARS,
    expected_returns,
    long_term_estimate,
)
from stock_analyzer.portfolio import Holding
from stock_analyzer.summary import build_summary


def _analysis(**overrides) -> HoldingAnalysis:
    defaults = dict(
        holding=Holding(symbol="7203.T", quantity=100, avg_cost=3000.0),
        name="Toyota",
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
        dividend_yield=2.0,
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
        industry="Auto",
        next_earnings=None,
        days_to_earnings=None,
    )
    defaults.update(overrides)
    return HoldingAnalysis(**defaults)


def test_long_term_estimate_positive_for_cheap_growing():
    pct, stars, reason = long_term_estimate(_analysis())
    assert pct is not None and pct > 0
    # 誠実ラベル: サンプル検証が無いので★★★★★には張り付かない
    assert stars is not None and stars.count("★") <= LONG_TERM_MAX_STARS
    assert reason  # 何らかの理由フレーズ


def test_long_term_estimate_none_without_data():
    a = _analysis(
        eps=None,
        target_mean_price=None,
        earnings_growth=None,
        revenue_growth=None,
        dividend_yield=None,
    )
    pct, stars, reason = long_term_estimate(a)
    assert pct is None and stars is None
    assert "データ不足" in reason


def test_expected_returns_three_horizons_and_labels():
    a = _analysis()
    summary = build_summary(a, "中立")
    # backtest 統計なし → 短中期はデータ不足、長期はモデル推定
    horizons = expected_returns(summary, a, None)
    labels = [h.label for h in horizons]
    assert labels == ["1週間", "1ヶ月", "半年〜1年"]

    short, mid, long = horizons
    assert short.basis == "検証実績" and short.pct is None  # 統計なし
    assert mid.basis == "検証実績" and mid.pct is None
    assert long.basis == "モデル推定" and long.pct is not None


def test_expected_returns_uses_backtest_when_present():
    a = _analysis()
    summary = build_summary(a, "中立")
    band = summary.price_score
    from stock_analyzer.backtest import band_label

    label = band_label(band)
    stats = {
        "rules": {
            "5営業日後売却": {"bands": {label: {"expectancy": 2.5, "count": 1500}}},
            "20営業日後売却": {"bands": {label: {"expectancy": 6.0, "count": 400}}},
        }
    }
    horizons = expected_returns(summary, a, stats)
    short, mid, _ = horizons
    assert short.pct == 2.5 and short.stars == "★★★★"  # count>=1000
    assert mid.pct == 6.0 and mid.stars == "★★★"  # count>=300
