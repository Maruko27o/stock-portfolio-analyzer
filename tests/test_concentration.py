from __future__ import annotations

from stock_analyzer import concentration, config
from stock_analyzer.decision import HoldingDecision, score_to_action
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.rebalance import DRIFT_TOLERANCE_PCT, RebalanceItem, RebalancePlan


def _decision(symbol="7203.T", score=90, action="強く買い増し", **kw) -> HoldingDecision:
    stars, _ = score_to_action(score)
    defaults = dict(
        name=symbol, current_price=1000.0, overall_score=score, overall_stars=stars,
        action=action, fair_value=1200.0, discount_pct=-8.0, risk_reward=2.0,
        supply_demand_stars="★★★★☆", dividend_stars="★★★☆☆", dividend_yield=3.0,
        days_to_earnings=None, earnings_alert=False,
        expected_returns=[HorizonExpectation("半年〜1年", 12.0, "★★★", "中", "モデル推定", "r")],
        comment="追加購入を検討", volatility_pct=2.0, sector="Industrials", reasons=["割安圏"],
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


def _plan(symbol, current_pct, target_pct):
    diff = target_pct - current_pct
    if abs(diff) < DRIFT_TOLERANCE_PCT:
        direction = "維持"
    elif diff > 0:
        direction = "買い増し"
    else:
        direction = "売却"
    item = RebalanceItem(
        symbol=symbol, name=symbol, current_pct=current_pct, target_pct=target_pct,
        diff_pct=diff, direction=direction, approx_shares=10, current_price=1000.0,
    )
    return RebalancePlan(items=[item], total_value_yen=1_000_000.0, note="n")


def test_overweight_buy_is_reconciled_to_trim():
    # 現在45% vs 目標25%: リバランスは縮小方向 → 買い増しカードを「一部売却(サイズ調整)」へ
    d = _decision(action="強く買い増し", score=92)
    changes = concentration.reconcile_with_rebalance([d], _plan("7203.T", 45.0, 25.0))
    assert len(changes) == 1
    assert d.action == "一部売却"
    assert d.sizing_trim is True
    # 銘柄の質(スコア)は据え置き、★は決定的関数(floor(92/20)=4)
    assert d.overall_score == 92
    assert d.overall_stars == "★★★★☆"
    assert any("サイズ調整" in r for r in d.reasons)


def test_within_tolerance_not_reconciled():
    # 現在27% vs 目標25%: 差2pt<許容3pt=維持方向 → 変更しない
    d = _decision(action="買い増し", score=75)
    changes = concentration.reconcile_with_rebalance([d], _plan("7203.T", 27.0, 25.0))
    assert changes == []
    assert d.action == "買い増し"


def test_neutral_card_with_reduce_becomes_trim():
    # 様子見(中立)カードでもリバランスが縮小方向なら一部売却へ整合(カテゴリ10の再発ケース)
    d = _decision(action="保有", score=64)
    changes = concentration.reconcile_with_rebalance([d], _plan("7203.T", 13.0, 5.0))
    assert d.action == "一部売却"
    assert d.sizing_trim is True


def test_is_overweight_thresholds():
    assert concentration.is_overweight(45.0, 25.0) is True
    assert concentration.is_overweight(27.0, 25.0) is False
    assert config.OVERWEIGHT_REL_THRESHOLD == 0.30
