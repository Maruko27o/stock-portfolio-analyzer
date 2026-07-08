from __future__ import annotations

from types import SimpleNamespace

from stock_analyzer import valuation
from stock_analyzer.allocation import AllocationPlan, optimize_allocation
from stock_analyzer.decision import (
    HoldingDecision,
    _price,
    stars_from_score,
    star_count,
)
from stock_analyzer.display import format_yen, should_show_allocation
from stock_analyzer.final_output import build_context, card_line_count
from stock_analyzer.horizon_model import HorizonExpectation


def _decision(symbol="A.T", score=75, action="買い増し", **kw) -> HoldingDecision:
    defaults = dict(
        name=symbol, current_price=1234.5, overall_score=score, overall_stars=stars_from_score(score),
        action=action, fair_value=1400.0, discount_pct=-12.0, risk_reward=2.0,
        supply_demand_stars="★★★☆☆", dividend_stars="★★★☆☆", dividend_yield=3.0,
        days_to_earnings=None, earnings_alert=False,
        expected_returns=[
            HorizonExpectation("1週間", 1.0, "★★", "中", "モデル推定", "a"),
            HorizonExpectation("1ヶ月", 3.0, "★★", "中", "モデル推定", "b"),
            HorizonExpectation("半年〜1年", 12.0, "★★★", "中", "モデル推定", "c"),
        ],
        comment="c", volatility_pct=2.0, sector="Industrials",
        reasons=["割安圏", "増益", "需給改善"], risks=["決算接近注意"],
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


# --- カテゴリ12: 星は決定的 floor(score/20) ---
def test_stars_deterministic_including_band_edges():
    cases = {0: 0, 19: 0, 20: 1, 40: 2, 79: 3, 80: 4, 84: 4, 85: 4, 99: 4, 100: 5}
    for score, n in cases.items():
        assert star_count(stars_from_score(score)) == n
    # 85点はアクション帯では最上位でも、★は floor(85/20)=4 に固定(+1個バグを封じる)
    assert stars_from_score(85) == "★★★★☆"


# --- カテゴリ13: 資金配分の表示可否は単一関数 ---
def test_should_show_allocation_truth_table():
    assert should_show_allocation("買い増し", 20.0) is True
    assert should_show_allocation("強く買い増し", 30.0) is True
    for action in ("保有", "様子見", "一部売却", "売却推奨"):
        assert should_show_allocation(action, 20.0) is False
    assert should_show_allocation("買い増し", None) is False
    assert should_show_allocation("買い増し", 0.0) is False


def test_hold_action_gets_no_allocation_in_optimizer():
    # 保有は新規配分の対象外(NO_ADD_ACTIONS)。alloc_pct が付かない。
    d = _decision("H.T", 80, action="保有")
    optimize_allocation([d], stance="中立", vix=15.0)
    assert not should_show_allocation(d.action, d.alloc_pct)


# --- カテゴリ11: 順位はスコア降順が起点 ---
def test_ranking_is_score_descending():
    # 高スコアだが期待リターン低い銘柄が、低スコア高期待より必ず上位
    high = _decision("HIGH.T", 90, expected_returns=[HorizonExpectation("半年〜1年", 1.0, "★", "低", "モデル推定", "r")])
    low = _decision("LOW.T", 60, expected_returns=[HorizonExpectation("半年〜1年", 30.0, "★★★★", "高", "モデル推定", "r")])
    plan = optimize_allocation([low, high], stance="中立", vix=15.0)
    assert [d.symbol for d in plan.ranking] == ["HIGH.T", "LOW.T"]
    assert plan.ranking[0].rank == 1
    # 順位は総合スコア降順に一致
    assert plan.ranking[0].overall_score >= plan.ranking[1].overall_score


# --- カテゴリ15: 金額フォーマットは一元・整数・カンマ・円 ---
def test_format_yen_is_integer_comma_yen():
    assert format_yen(1234.5) == "1,234円"
    assert format_yen(999.4) == "999円"
    assert format_yen(1000000) == "1,000,000円"
    assert format_yen(None) == "—"
    # 全金額ラッパが同一実装を経由(小数点2桁の不統一が無い)
    assert _price(1234.5) == "1,234円"
    assert "." not in _price(500.0)


# --- カテゴリ16: カード行数が目標範囲 ---
def test_card_line_count_within_target():
    d = _decision()
    ctx = build_context(SimpleNamespace(decisions=[d], allocation=None, gate_passed=True, violations=[], confidence=(90, "★★★★☆", [])))
    assert card_line_count(d, ctx) <= 8


# --- カテゴリ14: PER妥当性 ---
def _an(**kw):
    base = dict(eps=None, current_price=1000.0, sector="Technology",
                target_mean_price=None, target_high_price=None, target_low_price=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_per_plausible_band():
    # Technology 目安PER=25 → 妥当帯 ~[8.3, 75]
    assert valuation.per_is_plausible(20.0, "Technology") is True
    assert valuation.per_is_plausible(2.0, "Technology") is False   # 1/3未満=異常
    assert valuation.per_is_plausible(200.0, "Technology") is False  # 3倍超=異常
    assert valuation.per_is_plausible(None, "Technology") is False
    assert valuation.per_is_plausible(-5.0, "Technology") is False


def test_fair_value_excludes_bad_eps():
    # 実効PER=price/eps=1000/500=2 (異常) → EPS由来の適正価格を使わない。
    # アナリスト目標も無いので fair_value は None(誤った割安を出さない)。
    an = _an(eps=500.0, current_price=1000.0, sector="Technology")
    assert valuation.eps_based_fair_value_usable(an) is False
    assert valuation.fair_value(an) is None
    # 実効PER=25(妥当)なら EPS由来を使う
    an2 = _an(eps=40.0, current_price=1000.0, sector="Technology")
    assert valuation.eps_based_fair_value_usable(an2) is True
    assert valuation.fair_value(an2) is not None
