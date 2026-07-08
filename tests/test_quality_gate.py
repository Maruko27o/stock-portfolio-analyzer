from __future__ import annotations

from stock_analyzer import self_improve
from stock_analyzer.decision import HoldingDecision
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.quality_gate import confidence, gate_check, run_gate


def _decision(symbol="7203.T", **kw) -> HoldingDecision:
    defaults = dict(
        name=symbol, current_price=1000.0, overall_score=75, overall_stars="★★★★☆",
        action="買い増し", fair_value=1050.0, discount_pct=-5.0, risk_reward=2.0,
        supply_demand_stars="★★★☆☆", dividend_stars="★★★☆☆", dividend_yield=3.0,
        days_to_earnings=None, earnings_alert=False,
        expected_returns=[HorizonExpectation("半年〜1年", 12.0, "★★★", "中", "モデル推定", "r")],
        comment="追加購入を検討", volatility_pct=2.0, sector="Industrials", reasons=["割安圏"],
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


class _View:
    def __init__(self, decisions, allocation=None, review=None, gate_passed=False):
        self.decisions = decisions
        self.allocation = allocation
        self.review = review or []
        self.gate_passed = gate_passed


def test_gate_check_clean_passes():
    assert gate_check(_View([_decision()])) == []


def test_gate_flags_strong_buy_overvalued():
    d = _decision(action="強く買い増し", discount_pct=20.0, overall_score=95)
    issues = gate_check(_View([d]))
    assert any("極端に割高" in i for i in issues)


def test_gate_flags_sell_with_high_expected():
    d = _decision(action="売却推奨", overall_score=30,
                  expected_returns=[HorizonExpectation("半年〜1年", 20.0, "★★", "中", "モデル推定", "r")])
    issues = gate_check(_View([d]))
    assert any("売却判断だが期待リターンが高い" in i for i in issues)


def test_gate_flags_missing_price():
    issues = gate_check(_View([_decision(current_price=None)]))
    assert any("現在値が欠損" in i for i in issues)


def test_gate_flags_unsorted():
    ds = [_decision(symbol="A.T", overall_score=60), _decision(symbol="B.T", overall_score=90)]
    issues = gate_check(_View(ds))
    assert any("スコア降順" in i for i in issues)


def test_run_gate_bounces_to_self_improve_and_passes():
    d = _decision(risk_reward=0.3, action="買い増し")  # RR<1で買い=矛盾
    view = _View([d])
    assert gate_check(view)  # 最初は問題あり

    def on_fix():
        self_improve.improve(view.decisions, [])

    passed, passes, issues = run_gate(view, on_fix)
    assert passed is True
    assert issues == []
    assert 1 <= passes <= 3


def test_confidence_returns_pct_stars_reasons():
    view = _View([_decision()], gate_passed=True)
    pct, stars, reasons = confidence(view)
    assert 0 <= pct <= 100
    assert len(stars) == 5
    assert any("銘柄別信頼度の平均" in r for r in reasons)
    assert "品質ゲート通過" in reasons
