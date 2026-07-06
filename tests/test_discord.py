from unittest.mock import MagicMock, patch

import pytest

from stock_analyzer.allocation import AllocationPlan
from stock_analyzer.conclusion import ActionItem, DailyConclusion
from stock_analyzer.decision import HoldingDecision
from stock_analyzer.discord import (
    conclusion_embed,
    failed_embed,
    holding_embed,
    manager_embed,
    market_embed,
    send_discord,
    swing_embed,
)
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.rebalance import RebalanceItem, RebalancePlan


def _decision(**overrides) -> HoldingDecision:
    defaults = dict(
        symbol="7203.T",
        name="トヨタ自動車",
        current_price=3500.0,
        overall_score=88,
        overall_stars="★★★★★",
        action="強く買い増し",
        fair_value=3820.0,
        discount_pct=-8.4,
        risk_reward=2.8,
        supply_demand_stars="★★★★☆",
        dividend_stars="★★★★★",
        dividend_yield=4.24,
        days_to_earnings=15,
        earnings_alert=False,
        expected_returns=[
            HorizonExpectation("1週間", 2.8, "★★★★", "高", "検証実績", "短期テクニカル良好"),
            HorizonExpectation("1ヶ月", 6.4, "★★★", "中", "検証実績", "需給改善中"),
            HorizonExpectation("半年〜1年", 18.5, "★★★", "高", "モデル推定", "業績成長＋割安"),
        ],
        comment="保有中で最も優先して追加購入したい銘柄",
        profit_pct=16.7,
        rank=1,
        alloc_pct=25.0,
        sector="Consumer Cyclical",
    )
    defaults.update(overrides)
    return HoldingDecision(**defaults)


def test_holding_embed_has_color_title_and_key_decision_fields():
    embed = holding_embed(_decision())
    assert "7203.T トヨタ自動車" in embed["title"]
    assert "強く買い増し" in embed["title"]
    assert isinstance(embed["color"], int)
    desc = embed["description"]
    assert "総合スコア：88点 ★★★★★" in desc
    assert "買い順位 1位" in desc
    assert "資金配分 25%" in desc
    assert "半年〜1年 +18.5%(推定★★★)" in desc
    assert "💬 保有中で最も優先" in desc


def test_holding_embed_marks_earnings_alert():
    normal = holding_embed(_decision(days_to_earnings=15, earnings_alert=False))
    assert "決算まで 15日" in normal["description"]
    assert "⚠️" not in normal["description"]
    alert = holding_embed(_decision(days_to_earnings=3, earnings_alert=True))
    assert "⚠️" in alert["description"]


def test_holding_embed_handles_missing_data():
    embed = holding_embed(
        _decision(
            risk_reward=None,
            discount_pct=None,
            dividend_stars=None,
            profit_pct=None,
            alloc_pct=None,
        )
    )
    desc = embed["description"]
    assert "RR —" in desc
    assert "配当 —" in desc
    assert "保有損益" not in desc  # profit None のときは行ごと出さない


def _plan(**overrides) -> AllocationPlan:
    d1 = _decision(symbol="1928.T", name="積水ハウス", rank=1, alloc_pct=25.0, sector="Real Estate")
    d2 = _decision(symbol="8604.T", name="野村HD", rank=2, alloc_pct=20.0, sector="Financial Services")
    defaults = dict(
        ranking=[d1, d2],
        weights={"1928.T": 25.0, "8604.T": 20.0},
        cash_pct=55.0,
        sector_breakdown={"Real Estate": 25.0, "Financial Services": 20.0},
        expected_dividend_yield=3.4,
        portfolio_expected_return=12.5,
        portfolio_risk=1.8,
        diversification_note="概ね分散",
    )
    defaults.update(overrides)
    return AllocationPlan(**defaults)


def test_manager_embed_shows_ranking_allocation_and_caveat():
    embed = manager_embed(_plan())
    desc = embed["description"]
    assert "買い優先順位" in desc
    assert "1位 1928.T 積水ハウス" in desc
    assert "次の投資資金の配分" in desc
    assert "積水ハウス 25%" in desc
    assert "現金 55%" in desc
    assert "想定配当利回り 3.4%" in desc
    assert "帯間の勝率差は小さい" in desc  # スコアの但し書き(誠実ラベル)


def test_holding_embed_shows_tax_note():
    embed = holding_embed(_decision(tax_note="特定口座・含み益 10,000円。利益が小さく売却しやすい ※20万円以下の目安"))
    assert "🧾" in embed["description"]
    assert "特定口座・含み益" in embed["description"]


def test_manager_embed_shows_rebalance():
    reb = RebalancePlan(
        items=[
            RebalanceItem("1928.T", "積水ハウス", 40.0, 25.0, -15.0, "売却", 30, 3500.0),
            RebalanceItem("8604.T", "野村HD", 10.0, 20.0, 10.0, "買い増し", 20, 3500.0),
        ],
        total_value_yen=1_000_000.0,
        note="比率が高すぎる銘柄あり(縮小推奨)",
    )
    embed = manager_embed(_plan(), reb)
    desc = embed["description"]
    assert "リバランス(現在→推奨)" in desc
    assert "積水ハウス：40%→25%" in desc


def test_market_embed_lists_changes():
    embed = market_embed("強気", {"日経平均": (39000.0, 1.2)})
    assert "強気" in embed["title"]
    assert "日経平均" in embed["description"]


def test_market_embed_prefers_stance_and_shows_long_rate():
    embed = market_embed(
        "強気",
        {"日経平均": (39000.0, 1.2), "長期金利": (4.25, 3.0)},
        stance="やや強気",
    )
    assert "やや強気" in embed["title"]
    assert "長期金利(米10年): 4.25%" in embed["description"]


def test_conclusion_embed_do_nothing():
    c = DailyConclusion(
        do_nothing=True,
        headline=["本日は「何もしない」が最適。", "保有継続でOK。"],
        buys=[],
        sells=[],
        cash_pct=20.0,
    )
    embed = conclusion_embed(c)
    assert "本日の結論" in embed["title"]
    assert "何もしない" in embed["description"]


def test_conclusion_embed_with_actions():
    c = DailyConclusion(
        do_nothing=False,
        headline=["買い: A", "売り: B", "現金比率の推奨: 20%"],
        buys=[ActionItem("A.T", "A社", "買い増し", "★★★★☆・割安圏")],
        sells=[ActionItem("B.T", "B社", "売却推奨", "売却推奨・税負担軽く売りやすい")],
        cash_pct=20.0,
    )
    embed = conclusion_embed(c)
    desc = embed["description"]
    assert "今日の買い候補" in desc
    assert "A社" in desc
    assert "今日の売り候補" in desc
    assert "B社" in desc


def test_swing_embed_numbers_picks_and_has_disclaimer():
    embed = swing_embed(
        [{"heading": "1721.T A", "score": 100, "current_price": 5000.0, "reasons": ["r"]}]
    )
    assert "1. 1721.T A" in embed["description"]
    assert "保証するものではありません" in embed["description"]


def test_failed_embed_lists_symbols():
    assert "AAA, BBB" in failed_embed(["AAA", "BBB"])["description"]


def test_send_discord_posts_embeds_in_batches_of_ten():
    embeds = [{"title": str(i)} for i in range(23)]
    with patch("stock_analyzer.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=204)
        send_discord("https://hook", embeds)

    assert mock_post.call_count == 3  # 10 + 10 + 3
    for _, kwargs in mock_post.call_args_list:
        assert len(kwargs["json"]["embeds"]) <= 10


def test_send_discord_raises_on_error():
    with patch("stock_analyzer.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=400, text="bad")
        with pytest.raises(RuntimeError, match="Discord webhook error 400"):
            send_discord("https://hook", [{"title": "x"}])
