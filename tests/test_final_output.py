from __future__ import annotations

from stock_analyzer.decision import HoldingDecision
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.final_output import (
    build_context,
    final_card_lines,
    recommended_action,
)


def _decision(symbol="7203.T", **kw) -> HoldingDecision:
    defaults = dict(
        name="トヨタ", current_price=1000.0, overall_score=88, overall_stars="★★★★★",
        action="強く買い増し", fair_value=1200.0, discount_pct=-16.0, risk_reward=2.8,
        supply_demand_stars="★★★★☆", dividend_stars="★★★★☆", dividend_yield=3.0,
        days_to_earnings=None, earnings_alert=False,
        expected_returns=[
            HorizonExpectation("1週間", 2.0, "★★★★", "高", "検証実績", "a"),
            HorizonExpectation("1ヶ月", 5.0, "★★★", "中", "検証実績", "b"),
            HorizonExpectation("半年〜1年", 18.0, "★★★★", "高", "モデル推定", "c"),
        ],
        comment="最優先で追加購入", volatility_pct=2.0, sector="Industrials",
        rank=1, alloc_pct=25.0, reasons=["利益成長", "需給改善", "PER割安"],
        risks=["決算接近注意"],
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


class _View:
    def __init__(self, decisions, allocation=None):
        self.decisions = decisions
        self.allocation = allocation


def test_recommended_action_mapping():
    assert recommended_action(_decision(action="強く買い増し")) == "今すぐ買う"
    assert recommended_action(_decision(action="買い増し")) == "分割買い"
    assert recommended_action(_decision(action="保有")) == "様子見"
    assert recommended_action(_decision(action="保有", is_candidate=True)) == "押し目待ち"
    assert recommended_action(_decision(action="一部売却", profit_pct=10.0)) == "利益確定"
    assert recommended_action(_decision(action="売却推奨")) == "売却"


def test_recommended_action_appends_earnings_wait():
    out = recommended_action(_decision(action="買い増し", earnings_alert=True, days_to_earnings=3))
    assert "決算待ち" in out


def test_final_card_has_all_sections_and_keeps_numbers():
    d = _decision()
    ctx = build_context(_View([d]))
    lines = final_card_lines(d, ctx)
    text = "\n".join(lines)
    # コンパクト化しても分析上重要な数値は一切削らない [カテゴリ16]。
    assert "88点" in text
    assert "★★★★☆" in text  # floor(88/20)=4 [カテゴリ12]
    assert "-16.0%" in text  # 割安率
    assert "+18.0%" in text  # 長期期待
    assert "判断理由" in text
    assert "資金配分：25%" in text
    # スマホ1画面向け: 1銘柄は目標行数(6〜8行)に収まる [カテゴリ16c]。
    assert len(lines) <= 8


def test_watch_card_is_tagged_and_compact():
    d = _decision(is_candidate=True)
    ctx = build_context(_View([d]))
    lines = final_card_lines(d, ctx)
    assert "🔍監視" in lines[0]  # 監視カードは見出しにタグ
    assert len(lines) <= 8


def test_build_context_market_avg():
    ds = [_decision(symbol="A.T"), _decision(symbol="B.T",
          expected_returns=[HorizonExpectation("半年〜1年", 8.0, "★★", "中", "モデル推定", "c")])]
    ctx = build_context(_View(ds))
    assert ctx["market_avg"] == (18.0 + 8.0) / 2
