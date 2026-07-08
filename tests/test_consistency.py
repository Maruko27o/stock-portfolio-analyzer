from __future__ import annotations

from stock_analyzer import consistency
from stock_analyzer.allocation import AllocationPlan
from stock_analyzer.decision import HoldingDecision
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.rebalance import RebalanceItem, RebalancePlan


def _decision(symbol="7203.T", score=75, action="買い増し", discount=-5.0, **kw) -> HoldingDecision:
    defaults = dict(
        name=kw.pop("name", symbol), current_price=1000.0, overall_score=score,
        overall_stars="★★★★☆", action=action, fair_value=1050.0, discount_pct=discount,
        risk_reward=2.0, supply_demand_stars="★★★☆☆", dividend_stars="★★★☆☆",
        dividend_yield=3.0, days_to_earnings=None, earnings_alert=False,
        expected_returns=[HorizonExpectation("半年〜1年", 12.0, "★★★", "中", "モデル推定", "r")],
        comment="c", volatility_pct=2.0, sector="Industrials", reasons=["割安圏"],
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


class _View:
    def __init__(self, decisions, allocation=None, rebalance=None, gate_passed=True):
        self.decisions = decisions
        self.allocation = allocation
        self.rebalance = rebalance
        self.gate_passed = gate_passed
        self.violations = []


def _alloc(decisions):
    for i, d in enumerate(sorted(decisions, key=lambda x: x.overall_score, reverse=True), 1):
        d.rank = i
    return AllocationPlan(
        ranking=sorted(decisions, key=lambda x: x.overall_score, reverse=True),
        weights={}, cash_pct=10.0, sector_breakdown={}, expected_dividend_yield=None,
        portfolio_expected_return=None, portfolio_risk=None, diversification_note="n",
    )


def test_clean_report_has_no_violations():
    d = _decision(action="買い増し", score=72, discount=-5.0)
    view = _View([d], allocation=_alloc([d]))
    assert consistency.check_all(view) == []


def test_check1_action_vs_rebalance_contradiction():
    d = _decision(action="買い増し", score=72)
    item = RebalanceItem("7203.T", "t", 45.0, 25.0, -20.0, "売却", 10, 1000.0)
    view = _View([d], allocation=_alloc([d]), rebalance=RebalancePlan([item], 1.0, "n"))
    v = consistency.check_all(view)
    assert any(x.rule == "1.方向矛盾" for x in v)


def test_check2_overvalued_strong_buy():
    d = _decision(action="強く買い増し", score=90, discount=8.0)
    view = _View([d], allocation=_alloc([d]))
    v = consistency.check_all(view)
    assert any(x.rule == "2.割高強気" for x in v)


def test_check4_stars_out_of_range():
    d = _decision()
    d.supply_demand_stars = "★★★★★★"  # 6個
    view = _View([d], allocation=_alloc([d]))
    v = consistency.check_all(view)
    assert any(x.rule == "4.スター範囲外" for x in v)


def test_check5_negative_days():
    d = _decision(days_to_earnings=-74)
    view = _View([d], allocation=_alloc([d]))
    v = consistency.check_all(view)
    assert any(x.rule == "5.負の日数" for x in v)


def test_check6_duplicate_company():
    # トヨタ本体と米ADRは同一企業(エイリアス表)→重複
    a = _decision(symbol="7203.T", name="トヨタ自動車")
    b = _decision(symbol="TM", name="Toyota Motor ADR")
    view = _View([a, b], allocation=_alloc([a, b]))
    v = consistency.check_all(view)
    assert any(x.rule == "6.企業重複" for x in v)


def test_check7_gate_wording_guarded_when_failed():
    # 品質ゲート未通過 + 強い買い → guarded で即時文言が出ない=違反にならない
    d = _decision(action="強く買い増し", score=90, discount=-8.0)
    view = _View([d], allocation=_alloc([d]), gate_passed=False)
    v = [x for x in consistency.check_all(view) if x.rule == "7.未通過文言"]
    assert v == []
