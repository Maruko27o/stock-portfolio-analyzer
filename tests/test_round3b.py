from __future__ import annotations

from stock_analyzer import names
from stock_analyzer.decision import HoldingDecision, stars_from_score
from stock_analyzer.final_output import build_context, final_card_lines
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.quality_gate import decision_confidence


def _decision(symbol="A.T", score=75, action="買い増し", rank=1, **kw) -> HoldingDecision:
    defaults = dict(
        name=symbol, current_price=1000.0, overall_score=score, overall_stars=stars_from_score(score),
        action=action, fair_value=1100.0, discount_pct=-8.0, risk_reward=2.0,
        supply_demand_stars="★★★☆☆", dividend_stars="★★★☆☆", dividend_yield=3.0,
        days_to_earnings=None, earnings_alert=False, rank=rank,
        expected_returns=[HorizonExpectation("半年〜1年", 12.0, "★★★", "中", "モデル推定", "r")],
        comment="c", volatility_pct=2.0, sector="Industrials", reasons=["割安圏"],
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


class _View:
    def __init__(self, decisions, gate_passed=False):
        self.decisions = decisions
        self.allocation = None
        self.gate_passed = gate_passed
        self.violations = []
        self.stability_alerts = []
        self.confidence = (0, "", [])


# --- Fix1: 信頼度はゲート未通過でも銘柄別に変動する(60へ潰れない) ---
def test_confidence_varies_even_when_gate_failed():
    coherent = _decision("A.T", subscores={"technical": 15, "fundamental": 10, "market": 5})
    mixed = _decision("B.T", subscores={"technical": 15, "fundamental": -12})
    per_bad = _decision("C.T", per_flagged=True, subscores={"technical": 12, "fundamental": 8})
    view = _View([coherent, mixed, per_bad], gate_passed=False)
    pcts = [decision_confidence(d, view)[0] for d in view.decisions]
    assert len(set(pcts)) >= 2, pcts          # 一律でない
    assert max(pcts) > 60                       # 60に一律クリップされていない


def test_gate_fail_still_notes_reference_value():
    d = _decision(subscores={"technical": 10})
    _pct, _stars, reasons = decision_confidence(d, _View([d], gate_passed=False))
    assert any("参考値" in r for r in reasons)


# --- Fix3: 「買い順位」は買い方向のみ。非買いは対象外 ---
def test_buy_rank_shown_only_for_buy_actions():
    ctx = build_context(_View([]))
    buy = _decision(action="買い増し", rank=3)
    hold = _decision(action="様子見", rank=9)
    cand = _decision(action="保有", rank=20, is_candidate=True)
    buy_line = final_card_lines(buy, ctx)[1]
    hold_line = final_card_lines(hold, ctx)[1]
    cand_line = final_card_lines(cand, ctx)[1]
    assert "買い順位3位" in buy_line
    assert "対象外" in hold_line and "9位" not in hold_line
    assert "対象外" in cand_line and "20位" not in cand_line


# --- Fix5: 社名マスタに監視/候補の主要銘柄が入り日本語化される ---
def test_name_master_covers_watch_names():
    assert names.official_name("9202.T") == "ANAホールディングス"
    assert names.official_name("4307.T") == "野村総合研究所"
    assert names.official_name("7164.T") == "全国保証"
    assert names.official_name("7011.T") == "三菱重工業"
    # 英語取得名でも表示は正規マスタの日本語へ解決される(resolveが優先)
    assert names.resolve("9202.T", "ANA Holdings Inc.") == "ANAホールディングス"
    # ANA Holdings と ANAホールディングス は同一企業なので不一致にはならない(誤記ではない)
    assert names.name_matches("9202.T", "ANA Holdings Inc.") is True
    # 真の誤記(三菱USJ)は不一致として検出される
    assert names.name_matches("8306.T", "三菱USJ") is False
