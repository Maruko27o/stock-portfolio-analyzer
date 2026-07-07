from __future__ import annotations

from types import SimpleNamespace

from stock_analyzer.decision import HoldingDecision
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.review import REVIEW_SYSTEM_PROMPT, llm_review, rule_based_review


def _decision(symbol="7203.T", **kw) -> HoldingDecision:
    defaults = dict(
        name=symbol,
        current_price=1000.0,
        overall_score=80,
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
        comment="c",
        volatility_pct=2.0,
        sector="Industrials",
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


def _data(decisions, allocation=None):
    return SimpleNamespace(decisions=decisions, allocation=allocation)


def test_no_findings_returns_empty():
    assert rule_based_review(_data([_decision()])) == []


def test_overvalued_but_buy_is_flagged():
    d = _decision(discount_pct=15.0, action="強く買い増し")
    findings = rule_based_review(_data([d]))
    assert any("割高" in f.issue and f.category.startswith("1.") for f in findings)
    assert all(f.why and f.fix for f in findings)  # なぜ+どう直すが必ずある


def test_rr_below_one_with_buy_flagged():
    findings = rule_based_review(_data([_decision(risk_reward=0.4, action="買い増し")]))
    assert any("RR" in f.issue for f in findings)


def test_negative_expected_but_buy_flagged():
    d = _decision(expected_returns=[HorizonExpectation("半年〜1年", -5.0, "★★", "低", "モデル推定", "r")])
    findings = rule_based_review(_data([d]))
    assert any("マイナス" in f.issue for f in findings)


def test_too_many_high_scores_flagged():
    decisions = [_decision(symbol=f"{i}.T", overall_score=98) for i in range(4)]
    findings = rule_based_review(_data(decisions))
    assert any(f.category.startswith("7.") and "出すぎ" in f.issue for f in findings)


def test_expected_return_too_high_flagged():
    d = _decision(expected_returns=[HorizonExpectation("半年〜1年", 55.0, "★★★", "中", "モデル推定", "r")])
    findings = rule_based_review(_data([d]))
    assert any("高すぎ" in f.issue for f in findings)


def test_nisa_sell_flagged():
    d = _decision(action="売却推奨", overall_score=40, account="NISA", tax_sell_bias=-1)
    findings = rule_based_review(_data([d]))
    assert any("NISA" in f.issue and f.category.startswith("5.") for f in findings)


def test_sector_concentration_flagged():
    alloc = SimpleNamespace(sector_breakdown={"Technology": 60.0}, ranking=[])
    findings = rule_based_review(_data([_decision()], allocation=alloc))
    assert any("配分" in f.issue and f.category.startswith("5.") for f in findings)


def test_llm_review_without_key_returns_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm_review("some analysis text", api_key=None) is None
    assert "レビューAI" in REVIEW_SYSTEM_PROMPT
