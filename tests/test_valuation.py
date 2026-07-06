from __future__ import annotations

import pytest

from stock_analyzer.analysis import HoldingAnalysis
from stock_analyzer.indicators import SupportResistance
from stock_analyzer.portfolio import Holding
from stock_analyzer.valuation import analyst_upside_pct, discount_pct, fair_value


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
        sector="Consumer Cyclical",  # PER基準15
        industry="Auto",
        next_earnings=None,
        days_to_earnings=None,
    )
    defaults.update(overrides)
    return HoldingAnalysis(**defaults)


def test_fair_value_from_eps_only():
    # セクター基準PER15 × EPS250 = 3750(アナリスト目標なし)
    assert fair_value(_analysis(target_mean_price=None)) == pytest.approx(3750.0)


def test_fair_value_blends_analyst_target():
    # (3750 + 3900) / 2 = 3825
    a = _analysis(target_mean_price=3900.0)
    assert fair_value(a) == pytest.approx(3825.0)


def test_fair_value_none_when_no_inputs():
    assert fair_value(_analysis(eps=None, target_mean_price=None)) is None
    assert fair_value(_analysis(eps=-10.0, target_mean_price=None)) is None


def test_discount_pct_negative_when_cheap():
    a = _analysis(target_mean_price=None)  # fair 3750, price 3500
    assert discount_pct(a) == pytest.approx((3500 - 3750) / 3750 * 100)
    assert discount_pct(a) < 0


def test_analyst_upside():
    assert analyst_upside_pct(_analysis(target_mean_price=3850.0)) == pytest.approx(10.0)
    assert analyst_upside_pct(_analysis(target_mean_price=None)) is None
