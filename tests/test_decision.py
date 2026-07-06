from __future__ import annotations

import pytest

from stock_analyzer.analysis import HoldingAnalysis
from stock_analyzer.decision import (
    build_decision,
    dividend_stars,
    risk_reward,
    score_to_action,
    supply_demand_stars,
)
from stock_analyzer.horizon_model import expected_returns
from stock_analyzer.indicators import SupportResistance
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
        momentum=6.0,
        macd_result=None,
        bollinger=0.5,
        volume_signal="増加",
        volume_trend_ratio=1.6,
        volume_price_signal="価格上昇×出来高増加(強い上昇)",
        levels=SupportResistance(support=3200.0, resistance=3700.0),
        period_high=3800.0,
        period_low=2900.0,
        per=12.0,
        pbr=0.9,
        dividend_yield=4.2,
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


def test_score_to_action_boundaries():
    assert score_to_action(95) == ("★★★★★", "強く買い増し")
    assert score_to_action(85) == ("★★★★★", "強く買い増し")
    assert score_to_action(70) == ("★★★★☆", "買い増し")
    assert score_to_action(58) == ("★★★☆☆", "保有")
    assert score_to_action(43) == ("★★☆☆☆", "様子見")
    assert score_to_action(30) == ("★☆☆☆☆", "一部売却")
    assert score_to_action(10) == ("☆☆☆☆☆", "売却推奨")


def test_risk_reward():
    assert risk_reward(3500, 3700, 3200) == pytest.approx(200 / 300)
    # 目標が現在以下 / 損切が現在以上 → 計算不能
    assert risk_reward(3500, 3400, 3200) is None
    assert risk_reward(3500, 3700, 3600) is None
    assert risk_reward(None, 3700, 3200) is None


def test_supply_demand_stars_strong():
    stars = supply_demand_stars(_analysis())
    assert stars is not None and len(stars) == 5
    assert stars.count("★") >= 4  # 強い上昇+出来高増+モメンタム


def test_supply_demand_stars_weak():
    a = _analysis(
        volume_price_signal="価格下落×出来高増加(強い下落)",
        volume_trend_ratio=0.6,
        momentum=-8.0,
    )
    assert supply_demand_stars(a).count("★") <= 2


def test_dividend_stars_none_when_no_dividend():
    assert dividend_stars(_analysis(dividend_yield=None)) is None
    assert dividend_stars(_analysis(dividend_yield=0.0)) is None


def test_dividend_stars_high_for_sustainable_yield():
    stars = dividend_stars(_analysis())  # 4.2%利回り, payout0.3, 増益
    assert stars.count("★") >= 4


def test_dividend_stars_penalizes_high_payout():
    high = dividend_stars(_analysis(payout_ratio=0.9)).count("★")
    low = dividend_stars(_analysis(payout_ratio=0.3)).count("★")
    assert high < low


def test_build_decision_integration():
    a = _analysis()
    summary = build_summary(a, "強気")
    horizons = expected_returns(summary, a, None)
    decision = build_decision(summary, a, horizons)

    assert decision.symbol == "7203.T"
    assert decision.overall_score == summary.score
    assert decision.overall_stars == score_to_action(summary.score)[0]
    assert decision.action == score_to_action(summary.score)[1]
    assert decision.fair_value is not None
    assert decision.discount_pct is not None
    assert len(decision.expected_returns) == 3
    assert decision.comment  # 非空
    assert decision.rank is None and decision.alloc_pct is None  # 後埋め前


def test_build_decision_earnings_alert():
    a = _analysis(days_to_earnings=3)
    summary = build_summary(a, "中立")
    decision = build_decision(summary, a, expected_returns(summary, a, None))
    assert decision.earnings_alert is True
    assert "決算接近" in decision.comment
