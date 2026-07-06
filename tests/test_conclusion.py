from __future__ import annotations

from stock_analyzer.allocation import optimize_allocation
from stock_analyzer.conclusion import build_conclusion
from stock_analyzer.decision import HoldingDecision
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.rebalance import build_rebalance


def _decision(
    symbol: str,
    score: int,
    *,
    action: str = "保有",
    price: float = 1000.0,
    tax_sell_bias: int = 0,
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
        tax_sell_bias=tax_sell_bias,
        is_candidate=is_candidate,
    )


def test_do_nothing_when_balanced_and_no_signals():
    decisions = [
        _decision("A.T", 60, action="保有"),
        _decision("B.T", 60, action="保有"),
    ]
    alloc = optimize_allocation(list(decisions), regime="横ばい", vix=18.0)
    reb = build_rebalance(decisions, {"A.T": 100, "B.T": 100})
    c = build_conclusion(decisions, alloc, reb)
    assert c.do_nothing is True
    assert any("何もしない" in line for line in c.headline)


def test_buys_listed_when_add_signal():
    decisions = [
        _decision("BUY.T", 90, action="買い増し"),
        _decision("HOLD.T", 60, action="保有"),
    ]
    alloc = optimize_allocation(list(decisions), regime="上昇", vix=15.0)
    reb = build_rebalance(decisions, {"BUY.T": 100, "HOLD.T": 100})
    c = build_conclusion(decisions, alloc, reb)
    assert c.do_nothing is False
    assert "BUY.T" in [b.symbol for b in c.buys]
    assert any("買い" in line for line in c.headline)


def test_sells_ordered_by_tax_bias():
    # 売りやすい(bias +1)ほど先に並ぶ
    decisions = [
        _decision("NISA.T", 30, action="売却推奨", tax_sell_bias=-1),
        _decision("EASY.T", 30, action="売却推奨", tax_sell_bias=1),
    ]
    alloc = optimize_allocation(list(decisions), regime="横ばい", vix=18.0)
    reb = build_rebalance(decisions, {"NISA.T": 100, "EASY.T": 100})
    c = build_conclusion(decisions, alloc, reb)
    assert [s.symbol for s in c.sells] == ["EASY.T", "NISA.T"]


def test_headline_at_most_three_lines():
    decisions = [
        _decision("BUY.T", 90, action="強く買い増し"),
        _decision("SELL.T", 30, action="売却推奨"),
    ]
    alloc = optimize_allocation(list(decisions), regime="上昇", vix=15.0)
    reb = build_rebalance(decisions, {"BUY.T": 100, "SELL.T": 100})
    c = build_conclusion(decisions, alloc, reb)
    assert len(c.headline) <= 3


def test_buy_signal_excluded_from_rebalance_trim():
    # 買いシグナルのある銘柄は「比率是正(縮小)」に出さない(買い/売り両方に出る矛盾を防ぐ)。
    over = _decision("OVER.T", 88, action="買い増し", price=1000.0)
    small = _decision("SMALL.T", 60, action="保有", price=1000.0)
    decisions = [over, small]
    alloc = optimize_allocation(list(decisions), regime="上昇", vix=15.0)
    # OVER を持ちすぎ(70%) → リバランスは縮小方向だが、買いシグナルなので是正から除外
    reb = build_rebalance(decisions, {"OVER.T": 700, "SMALL.T": 300})
    c = build_conclusion(decisions, alloc, reb)
    assert "OVER.T" in [b.symbol for b in c.buys]
    assert "OVER.T" not in [m.symbol for m in c.rebalance_moves]


def test_candidate_can_be_a_buy():
    decisions = [_decision("HELD.T", 55, action="様子見")]
    candidate = _decision("NEW.T", 92, action="買い増し", is_candidate=True)
    alloc = optimize_allocation([*decisions, candidate], regime="上昇", vix=15.0)
    reb = build_rebalance(decisions, {"HELD.T": 100})
    c = build_conclusion(decisions, alloc, reb)
    assert "NEW.T" in [b.symbol for b in c.buys]
    assert any(b.is_candidate for b in c.buys)
