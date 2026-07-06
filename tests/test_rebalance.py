from __future__ import annotations

import pytest

from stock_analyzer.decision import HoldingDecision
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.rebalance import build_rebalance


def _decision(
    symbol: str,
    score: int,
    *,
    action: str = "保有",
    price: float = 1000.0,
    is_candidate: bool = False,
) -> HoldingDecision:
    return HoldingDecision(
        symbol=symbol,
        name=symbol,
        current_price=price,
        overall_score=score,
        overall_stars="★★★☆☆",
        action=action,
        fair_value=1100.0,
        discount_pct=-5.0,
        risk_reward=2.0,
        supply_demand_stars="★★★☆☆",
        dividend_stars="★★★☆☆",
        dividend_yield=3.0,
        days_to_earnings=None,
        earnings_alert=False,
        expected_returns=[HorizonExpectation("半年〜1年", 10.0, "★★★", "中", "モデル推定", "r")],
        comment="c",
        volatility_pct=2.0,
        sector="Industrials",
        is_candidate=is_candidate,
    )


def test_current_weights_reflect_market_value():
    decisions = [
        _decision("A.T", 80, price=1000.0),
        _decision("B.T", 80, price=1000.0),
    ]
    # A を 400株、B を 100株 → 評価額 40万 : 10万 = 80% : 20%
    plan = build_rebalance(decisions, {"A.T": 400, "B.T": 100})
    by_symbol = {it.symbol: it for it in plan.items}
    assert by_symbol["A.T"].current_pct == pytest.approx(80.0)
    assert by_symbol["B.T"].current_pct == pytest.approx(20.0)
    assert plan.total_value_yen == pytest.approx(500000.0)


def test_overweight_equal_score_is_trimmed():
    # 同スコアなら推奨は均等寄り。40%/60%の偏りは是正方向。
    decisions = [
        _decision("BIG.T", 80, price=1000.0),
        _decision("SMALL.T", 80, price=1000.0),
    ]
    plan = build_rebalance(decisions, {"BIG.T": 600, "SMALL.T": 400})
    big = next(it for it in plan.items if it.symbol == "BIG.T")
    assert big.current_pct == pytest.approx(60.0)
    assert big.target_pct < big.current_pct  # 縮小方向
    assert big.direction == "売却"
    assert big.approx_shares is not None and big.approx_shares > 0


def test_sell_signal_reduces_target():
    decisions = [
        _decision("KEEP.T", 80, action="保有", price=1000.0),
        _decision("DUMP.T", 80, action="売却推奨", price=1000.0),
    ]
    plan = build_rebalance(decisions, {"KEEP.T": 500, "DUMP.T": 500})
    dump = next(it for it in plan.items if it.symbol == "DUMP.T")
    # 売却推奨は抑制係数0 → 推奨比率ほぼ0、売却方向
    assert dump.target_pct == pytest.approx(0.0, abs=1.0)
    assert dump.direction == "売却"


def test_candidates_excluded():
    decisions = [
        _decision("HELD.T", 80),
        _decision("NEW.T", 90, is_candidate=True),
    ]
    plan = build_rebalance(decisions, {"HELD.T": 100})
    assert [it.symbol for it in plan.items] == ["HELD.T"]


def test_small_drift_is_kept():
    # 均等でスコアも同じ → 乖離が許容範囲内なら「維持」
    decisions = [_decision("A.T", 80), _decision("B.T", 80)]
    plan = build_rebalance(decisions, {"A.T": 100, "B.T": 100})
    assert all(it.direction == "維持" for it in plan.items)


def test_empty_when_no_quantities():
    decisions = [_decision("A.T", 80)]
    plan = build_rebalance(decisions, {})
    assert plan.items == []
    assert plan.total_value_yen is None
