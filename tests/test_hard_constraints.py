from __future__ import annotations

from stock_analyzer import config
from stock_analyzer.allocation import AllocationPlan, optimize_allocation
from stock_analyzer.decision import HoldingDecision, apply_overvalued_cap
from stock_analyzer.final_output import recommended_action
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.quality_gate import confidence


def _decision(symbol="A.T", score=90, action="強く買い増し", discount=8.0, **kw) -> HoldingDecision:
    defaults = dict(
        name=symbol, current_price=1000.0, overall_score=score, overall_stars="★★★★★",
        action=action, fair_value=950.0, discount_pct=discount, risk_reward=2.0,
        supply_demand_stars="★★★☆☆", dividend_stars="★★★☆☆", dividend_yield=3.0,
        days_to_earnings=None, earnings_alert=False,
        expected_returns=[HorizonExpectation("半年〜1年", 10.0, "★★★", "中", "モデル推定", "r")],
        comment="c", volatility_pct=2.0, sector="Industrials",
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


# --- カテゴリ2: 割高のハード制約 ---
def test_apply_overvalued_cap_blocks_strong_buy():
    score, stars, action = apply_overvalued_cap(95, discount=8.0)
    assert score <= config.OVERVALUED_SCORE_CAP
    assert action != "強く買い増し"


def test_apply_overvalued_cap_leaves_cheap_alone():
    score, stars, action = apply_overvalued_cap(95, discount=-8.0)
    assert score == 95
    assert action == "強く買い増し"


# --- カテゴリ8: 現金比率が市場スタンスに連動 ---
def test_cash_floor_tracks_stance():
    d = [_decision("A.T", 95, action="買い増し", discount=-5.0, sector="Technology")]
    bull = optimize_allocation(list(d), stance="強気", vix=15.0)
    bear = optimize_allocation(list(d), stance="弱気", vix=15.0)
    assert bear.cash_pct >= bull.cash_pct
    assert bear.cash_range == (15.0, 25.0)
    assert bull.cash_range == (5.0, 10.0)


# --- カテゴリ9: 品質未通過で信頼度引き下げ & 即時文言の抑止 ---
class _View:
    def __init__(self, decisions, gate_passed, violations=None):
        self.decisions = decisions
        self.allocation = None
        self.review = []
        self.gate_passed = gate_passed
        self.violations = violations or []


def test_confidence_capped_when_gate_failed():
    d = _decision(action="買い増し", discount=-5.0)
    passed = confidence(_View([d], gate_passed=True))
    failed = confidence(_View([d], gate_passed=False))
    assert failed[0] <= config.OVERVALUED_SCORE_CAP  # 参考: 60以下
    assert failed[0] <= 60
    assert failed[0] < passed[0]
    assert any("参考値" in r for r in failed[2])


def test_recommended_action_guarded_suppresses_immediate():
    d = _decision(action="強く買い増し", discount=-8.0)
    assert recommended_action(d, guarded=False) == "今すぐ買う"
    assert recommended_action(d, guarded=True) != "今すぐ買う"
