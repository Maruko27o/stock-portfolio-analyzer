"""collect_report_data の分岐(保有・監視・スイング本格分析ファネル)をmockで検証する。

ネットワーク取得(_analyze_with_retry)と要約/判断の生成(_enriched_summary/_decision_from)を
差し替え、切り分け(held/watch/candidate)と TOP3 の並びだけを確認する。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from stock_analyzer.cli import collect_report_data
from stock_analyzer.decision import HoldingDecision
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.portfolio import Holding

SCORES = {"AAA": 80, "WATCH.T": 60, "CAND1.T": 90, "CAND2.T": 70}


def _decision(symbol: str) -> HoldingDecision:
    return HoldingDecision(
        symbol=symbol,
        name=symbol,
        current_price=1000.0,
        overall_score=SCORES.get(symbol, 50),
        overall_stars="★★★★☆",
        action="買い増し",
        fair_value=1100.0,
        discount_pct=-8.0,
        risk_reward=2.0,
        supply_demand_stars="★★★☆☆",
        dividend_stars="★★★☆☆",
        dividend_yield=3.0,
        days_to_earnings=None,
        earnings_alert=False,
        expected_returns=[HorizonExpectation("半年〜1年", 15.0, "★★★", "中", "モデル推定", "r")],
        comment="c",
        volatility_pct=2.0,
        sector="Industrials",
    )


def _run(holdings):
    with patch("stock_analyzer.cli.fetch_market_snapshot", return_value={"日経平均": (39000.0, 1.0)}), patch(
        "stock_analyzer.cli.evaluate_market_sentiment", return_value="強気"
    ), patch("stock_analyzer.cli._benchmark_context", return_value=(None, None)), patch(
        "stock_analyzer.cli.load_stats", return_value=None
    ), patch("stock_analyzer.cli.load_strategy_stats", return_value=None), patch(
        "stock_analyzer.cli.current_market_regime", return_value="上昇"
    ), patch(
        "stock_analyzer.cli._analyze_with_retry", side_effect=lambda h: h
    ), patch(
        "stock_analyzer.cli._enriched_summary",
        side_effect=lambda analysis, *a, **k: SimpleNamespace(
            symbol=analysis.symbol, raw_score=SCORES.get(analysis.symbol, 50)
        ),
    ), patch(
        "stock_analyzer.cli._decision_from",
        side_effect=lambda summary, analysis, backtest: _decision(analysis.symbol),
    ), patch(
        "stock_analyzer.cli.prescreen_symbols", return_value=["CAND1.T", "CAND2.T"]
    ):
        return collect_report_data(holdings)


def test_watch_holding_becomes_candidate_card():
    data = _run([Holding("AAA", 10, 100.0), Holding("WATCH.T", 0, 0.0)])
    by_symbol = {d.symbol: d for d in data.decisions}
    assert by_symbol["AAA"].is_candidate is False  # 保有
    assert by_symbol["WATCH.T"].is_candidate is True  # 監視(未保有)
    # 新規候補(スイング)は保有カードには出さない
    assert "CAND1.T" not in by_symbol


def test_swing_top3_from_full_analysis_sorted_by_priority():
    data = _run([Holding("AAA", 10, 100.0)])
    # 候補は優先度(スコア+期待)の高い順。CAND1(90) > CAND2(70)
    assert [p["heading"].split()[0] for p in data.swing_picks] == ["CAND1.T", "CAND2.T"]
    # 根拠は保有株と同じ観点(割安率・期待リターン)で構成される
    joined = " ".join(data.swing_picks[0]["reasons"])
    assert "割安率" in joined
    assert "半年〜1年 期待" in joined


def test_rebalance_only_targets_held_not_watch():
    data = _run([Holding("AAA", 10, 100.0), Holding("WATCH.T", 0, 0.0)])
    # リバランス対象は保有(AAA)のみ。監視・候補は含めない。
    assert data.rebalance is not None
    assert all(item.symbol == "AAA" for item in data.rebalance.items)
