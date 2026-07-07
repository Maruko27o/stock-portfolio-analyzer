from __future__ import annotations

from stock_analyzer.decision import HoldingDecision
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.review import rule_based_review
from stock_analyzer.self_score import DIMENSIONS, evaluate, refine


def _decision(symbol="7203.T", **kw) -> HoldingDecision:
    defaults = dict(
        name=symbol,
        current_price=1000.0,
        overall_score=75,
        overall_stars="★★★★☆",
        action="買い増し",
        fair_value=1050.0,
        discount_pct=-5.0,
        risk_reward=2.0,
        supply_demand_stars="★★★☆☆",
        dividend_stars="★★★☆☆",
        dividend_yield=3.0,
        days_to_earnings=None,
        earnings_alert=False,
        expected_returns=[HorizonExpectation("半年〜1年", 12.0, "★★★", "中", "モデル推定", "r")],
        comment="追加購入を検討",
        volatility_pct=2.0,
        sector="Industrials",
        reasons=["割安圏", "増収"],
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


def test_evaluate_returns_all_dimensions():
    scores = evaluate([_decision()], None, [])
    assert set(scores) == set(DIMENSIONS)
    assert all(0 <= v <= 100 for v in scores.values())


def test_clean_report_scores_high():
    scores = evaluate([_decision(), _decision(symbol="6758.T")], None, [])
    assert all(v >= 90 for v in scores.values()), scores


def test_missing_reasons_lowers_then_refine_supplements():
    d = _decision(reasons=[], comment="")
    before = evaluate([d], None, [])
    assert before["説明性"] < 90
    refine([d], [], None)
    assert d.reasons  # 根拠が補われた
    after = evaluate([d], None, [])
    assert after["説明性"] > before["説明性"]


def test_earnings_buy_lowers_risk_then_refine_downgrades():
    d = _decision(earnings_alert=True, days_to_earnings=2, action="買い増し")
    before = evaluate([d], None, [])
    assert before["リスク管理"] < 90
    refine([d], [], None)
    assert d.action == "保有"  # 決算跨ぎの買いは据え置きに修正


def test_refine_resolves_contradiction_dimensions():
    # RR<1で買い(整合性/分析精度が下がる) → refine で解消
    d = _decision(risk_reward=0.3, action="買い増し")
    assert rule_based_review(_View([d]))  # 指摘あり
    refine([d], [], None)
    assert rule_based_review(_View([d])) == []  # 解消


class _View:
    def __init__(self, decisions, allocation=None):
        self.decisions = decisions
        self.allocation = allocation
