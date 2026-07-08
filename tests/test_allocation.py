from __future__ import annotations

import pytest

from stock_analyzer import config
from stock_analyzer.allocation import optimize_allocation, priority_value
from stock_analyzer.decision import HoldingDecision
from stock_analyzer.horizon_model import HorizonExpectation


def _decision(
    symbol: str,
    score: int,
    *,
    action: str = "買い増し",
    sector: str = "Industrials",
    lt_pct: float | None = 10.0,
    lt_stars: str | None = "★★★",
    dividend_yield: float | None = 3.0,
    volatility: float | None = 2.0,
) -> HoldingDecision:
    horizons = [
        HorizonExpectation("半年〜1年", lt_pct, lt_stars, "中", "モデル推定", "理由"),
    ]
    stars, _ = "★★★★☆", action
    return HoldingDecision(
        symbol=symbol,
        name=symbol,
        current_price=1000.0,
        overall_score=score,
        overall_stars=stars,
        action=action,
        fair_value=1100.0,
        discount_pct=-5.0,
        risk_reward=2.0,
        supply_demand_stars="★★★★☆",
        dividend_stars="★★★★☆",
        dividend_yield=dividend_yield,
        days_to_earnings=None,
        earnings_alert=False,
        expected_returns=horizons,
        comment="c",
        volatility_pct=volatility,
        sector=sector,
    )


def test_weighted_avg_skips_nan():
    from stock_analyzer.allocation import _weighted_avg

    # NaN が混ざっても全体が nan にならず、有効値だけで平均する
    assert _weighted_avg([(0.5, 10.0), (0.5, float("nan"))]) == 10.0
    assert _weighted_avg([(0.5, None), (0.5, float("nan"))]) is None


def test_weights_and_cash_sum_to_100():
    decisions = [
        _decision("A.T", 90, sector="Technology"),
        _decision("B.T", 80, sector="Healthcare"),
        _decision("C.T", 70, sector="Industrials"),
    ]
    plan = optimize_allocation(decisions, stance="中立", vix=15.0)
    assert pytest.approx(sum(plan.weights.values()) + plan.cash_pct, abs=1e-6) == 100.0
    # 上昇相場の現金下限10%は守られる
    assert plan.cash_pct >= config.cash_range_for_stance("中立")[0] * 100 - 1e-6


def test_ranking_orders_by_priority():
    decisions = [
        _decision("LOW.T", 60, lt_pct=2.0, lt_stars="★"),
        _decision("HIGH.T", 92, lt_pct=20.0, lt_stars="★★★★"),
        _decision("MID.T", 75, lt_pct=8.0, lt_stars="★★"),
    ]
    plan = optimize_allocation(decisions, stance="中立", vix=15.0)
    assert [d.symbol for d in plan.ranking] == ["HIGH.T", "MID.T", "LOW.T"]
    assert plan.ranking[0].rank == 1
    assert priority_value(plan.ranking[0]) > priority_value(plan.ranking[1])


def test_name_cap_enforced():
    # 1銘柄だけ極端に魅力的でも銘柄上限30%を超えない
    decisions = [
        _decision("BIG.T", 100, lt_pct=30.0, lt_stars="★★★★"),
        _decision("SMALL.T", 50),
    ]
    plan = optimize_allocation(decisions, stance="中立", vix=15.0)
    assert plan.weights["BIG.T"] <= config.ALLOC_NAME_CAP * 100 + 1e-6


def test_sector_cap_enforced():
    decisions = [
        _decision("A.T", 95, sector="Technology"),
        _decision("B.T", 93, sector="Technology"),
        _decision("C.T", 90, sector="Technology"),
        _decision("D.T", 88, sector="Utilities"),
    ]
    plan = optimize_allocation(decisions, stance="中立", vix=15.0)
    tech = sum(v for s, v in plan.weights.items() if s in ("A.T", "B.T", "C.T"))
    assert tech <= config.ALLOC_SECTOR_CAP * 100 + 1e-6


def test_no_eligible_names_all_cash():
    decisions = [
        _decision("A.T", 40, action="様子見"),
        _decision("B.T", 20, action="売却推奨"),
    ]
    plan = optimize_allocation(decisions, stance="やや弱気", vix=18.0)
    assert plan.weights == {}
    assert plan.cash_pct == pytest.approx(100.0)


def test_risk_off_raises_cash_floor():
    decisions = [_decision("A.T", 95, sector="Technology")]
    plan = optimize_allocation(decisions, stance="強気", vix=32.0)
    assert plan.cash_pct >= config.VIX_RISK_OFF_CASH_FLOOR * 100 - 1e-6


def test_portfolio_metrics_are_weighted_averages():
    decisions = [
        _decision("A.T", 90, sector="Technology", dividend_yield=4.0, lt_pct=12.0, volatility=3.0),
        _decision("B.T", 80, sector="Healthcare", dividend_yield=2.0, lt_pct=6.0, volatility=1.0),
    ]
    plan = optimize_allocation(decisions, stance="中立", vix=15.0)
    assert plan.expected_dividend_yield is not None
    assert plan.portfolio_expected_return is not None
    assert plan.portfolio_risk is not None
    # 加重平均なので構成銘柄の値の範囲内に収まる
    assert 2.0 <= plan.expected_dividend_yield <= 4.0
    assert 6.0 <= plan.portfolio_expected_return <= 12.0
    assert 1.0 <= plan.portfolio_risk <= 3.0
