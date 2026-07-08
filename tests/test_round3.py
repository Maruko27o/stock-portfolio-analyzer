from __future__ import annotations

from types import SimpleNamespace

from stock_analyzer import consistency, names, ranking, valuation
from stock_analyzer.decision import (
    HoldingDecision,
    apply_rsi_extreme_cap,
    stars_from_score,
)
from stock_analyzer.final_output import recommended_action
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.quality_gate import decision_confidence


def _decision(symbol="A.T", score=75, action="買い増し", **kw) -> HoldingDecision:
    defaults = dict(
        name=symbol, current_price=1000.0, overall_score=score, overall_stars=stars_from_score(score),
        action=action, fair_value=1100.0, discount_pct=-8.0, risk_reward=2.0,
        supply_demand_stars="★★★☆☆", dividend_stars="★★★☆☆", dividend_yield=3.0,
        days_to_earnings=None, earnings_alert=False,
        expected_returns=[HorizonExpectation("半年〜1年", 12.0, "★★★", "中", "モデル推定", "r")],
        comment="c", volatility_pct=2.0, sector="Industrials", reasons=["割安圏"],
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


class _View:
    def __init__(self, decisions, **kw):
        self.decisions = decisions
        self.allocation = kw.get("allocation")
        self.rebalance = kw.get("rebalance")
        self.conclusion = kw.get("conclusion")
        self.swing_picks = kw.get("swing_picks", [])
        self.gate_passed = kw.get("gate_passed", True)
        self.violations = []
        self.stability_alerts = kw.get("stability_alerts", [])


# --- カテゴリ17: 個別カードにポート文言を混入しない ---
def test_recommended_action_never_has_portfolio_wording():
    for action in ["強く買い増し", "買い増し", "保有", "様子見", "一部売却", "売却推奨"]:
        label = recommended_action(_decision(action=action))
        assert not any(w in label for w in consistency.PORTFOLIO_WORDING), label


# --- カテゴリ18: 共通ソートは総合スコア降順 ---
def test_ranking_by_score_desc():
    ds = [_decision("A.T", 57), _decision("B.T", 65), _decision("C.T", 60)]
    out = ranking.by_score(ds)
    assert [d.overall_score for d in out] == [65, 60, 57]


def test_swing_ranking_check_flags_out_of_order():
    view = _View([_decision()], swing_picks=[{"heading": "A.T x", "score": 57},
                                             {"heading": "B.T y", "score": 65}])
    v = consistency.check_all(view)
    assert any(x.rule == "18.候補順位" for x in v)


# --- カテゴリ19: 銘柄別に信頼度が変動する ---
def test_confidence_varies_by_inputs():
    strong = _decision("S.T", subscores={"technical": 15, "fundamental": 10, "market": 5})
    mixed = _decision("M.T", subscores={"technical": 15, "fundamental": -12, "market": 3})
    thin = _decision("T.T", current_price=None, discount_pct=None, dividend_yield=None,
                     supply_demand_stars=None, subscores={})
    view = _View([strong, mixed, thin], gate_passed=True)
    pcts = {d.symbol: decision_confidence(d, view)[0] for d in view.decisions}
    assert len({*pcts.values()}) >= 2, pcts  # 一律でない


def test_confidence_variance_check_fires_on_uniform():
    ds = [_decision(f"{i}.T", 70) for i in range(6)]
    for d in ds:
        d.confidence_pct = 60
    v = consistency.check_all(_View(ds))
    assert any(x.rule == "19.信頼度一律" for x in v)


# --- カテゴリ20: 適正価格の桁乖離 ---
def test_fair_value_sanity():
    assert valuation.fair_value_is_sane(1100.0, 1000.0) is True
    assert valuation.fair_value_is_sane(9000.0, 1000.0) is False   # 9倍=桁乖離
    assert valuation.fair_value_is_sane(100.0, 1000.0) is False    # 1/10=桁乖離
    assert valuation.fair_value_is_sane(None, 1000.0) is True


def test_valuation_flagged_excluded_from_discount():
    d = _decision(valuation_flagged=True, discount_pct=-50.0)
    v = consistency.check_all(_View([d]))
    assert any(x.rule == "20.適正価格乖離" for x in v)  # 桁乖離なのに割安率が残る


# --- カテゴリ21: セクション内のティッカー重複 ---
def test_conclusion_dedup_removes_duplicate_sells():
    from stock_analyzer.conclusion import build_conclusion
    d1 = _decision("INPEX.T", 30, action="売却推奨")
    d2 = _decision("INPEX.T", 28, action="一部売却")  # 同一ティッカーが2回
    concl = build_conclusion([d1, d2], None, None)
    assert [it.symbol for it in concl.sells].count("INPEX.T") == 1


# --- カテゴリ22: 社名マスタ ---
def test_name_master_resolves_and_flags():
    assert names.official_name("8306.T") == "三菱UFJフィナンシャル・グループ"
    assert names.name_matches("8306.T", "三菱USJ") is False
    assert names.name_matches("8306.T", "三菱UFJフィナンシャル・グループ") is True
    assert names.name_matches("9999.T", "何でも") is True  # マスタ外は検証対象外
    assert names.resolve("8306.T", "三菱USJ") == "三菱UFJフィナンシャル・グループ"


def test_name_mismatch_check():
    d = _decision("8306.T", name="三菱USJ")
    d.name_mismatch = True
    v = consistency.check_all(_View([d]))
    assert any(x.rule == "22.社名不一致" for x in v)


# --- カテゴリ23: RSI極端過熱 ---
def test_rsi_extreme_caps_aggressive_buy():
    assert apply_rsi_extreme_cap("強く買い増し", 92.0) == "様子見"
    assert apply_rsi_extreme_cap("買い増し", 88.0) == "様子見"
    assert apply_rsi_extreme_cap("買い増し", 70.0) == "買い増し"  # 過熱でなければ据え置き


def test_rsi_extreme_consistency_check():
    d = _decision("H.T", 80, action="買い増し", rsi=92.0)
    v = consistency.check_all(_View([d]))
    assert any(x.rule == "23.過熱買い" for x in v)
