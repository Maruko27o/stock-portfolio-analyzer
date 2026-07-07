from __future__ import annotations

from types import SimpleNamespace

from stock_analyzer.decision import HoldingDecision
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.review import rule_based_review
from stock_analyzer.self_improve import (
    IMPROVE_SYSTEM_PROMPT,
    format_revision_lines,
    improve,
    llm_revise,
)


def _decision(symbol="7203.T", lt_pct=12.0, lt_stars="★★★", **kw) -> HoldingDecision:
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
        expected_returns=[HorizonExpectation("半年〜1年", lt_pct, lt_stars, "中", "モデル推定", "r")],
        comment="c",
        volatility_pct=2.0,
        sector="Industrials",
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


def test_caps_over_high_expected_return():
    d = _decision(lt_pct=55.0)
    revs = improve([d])
    assert d.expected_returns[0].pct == 40.0
    assert any("40%" in r.change for r in revs)


def test_rr_below_one_downgrades_buy():
    d = _decision(risk_reward=0.5, action="買い増し", overall_score=80)
    improve([d])
    assert d.action == "様子見"
    assert d.overall_score <= 57  # 点数も新しい帯へ再計算


def test_overvalued_buy_is_weakened():
    d = _decision(discount_pct=15.0, action="強く買い増し", overall_score=90)
    improve([d])
    assert d.action != "強く買い増し"


def test_negative_expected_buy_becomes_hold():
    d = _decision(lt_pct=-4.0, action="買い増し")
    improve([d])
    assert d.action == "保有"


def test_low_confidence_strong_buy_downgraded():
    d = _decision(action="強く買い増し", overall_score=92, lt_stars="★")
    improve([d])
    assert d.action == "買い増し"
    assert d.overall_score <= 84


def test_nisa_sell_becomes_hold():
    d = _decision(action="売却推奨", overall_score=40, account="NISA", tax_sell_bias=-1)
    improve([d])
    assert d.action == "保有"


def test_high_score_normalization():
    ds = [_decision(symbol=f"{i}.T", overall_score=99) for i in range(5)]
    improve(ds)
    still_high = [d for d in ds if d.overall_score >= 95]
    assert len(still_high) <= 3


def test_review_is_clean_after_improve():
    # レビューで指摘 → 改修 → 再レビューで消えることを確認(100%反映)
    ds = [
        _decision(symbol="A.T", risk_reward=0.4, action="買い増し"),
        _decision(symbol="B.T", lt_pct=60.0),
    ]
    data = SimpleNamespace(decisions=ds, allocation=None)
    assert rule_based_review(data)  # 改修前は指摘あり
    improve(ds)
    assert rule_based_review(data) == []  # 改修後は改善不要


def test_no_revisions_when_clean():
    assert improve([_decision()]) == []
    assert format_revision_lines([]) == ["🔧 自己改修", "レビュー指摘なし(修正不要)"]


def test_llm_revise_without_key_returns_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm_revise("analysis", "review", api_key=None) is None
    assert "改善AI" in IMPROVE_SYSTEM_PROMPT
