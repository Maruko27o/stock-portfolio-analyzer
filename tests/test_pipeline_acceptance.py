"""受け入れテスト: パイプライン最終段の必須検証(7項目)を全銘柄へ一括実行し、
違反ゼロを確認する。故意に矛盾を仕込んだ入力が自己改修ループで解消されることも見る。

ライブ株価はこの環境では取得不可のため、analyze/summary/decision をモックし、
実運用と同じ collect_report_data のフロー(改修→ゲート→整合チェック)を通す。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from stock_analyzer.cli import collect_report_data
from stock_analyzer.decision import HoldingDecision, stars_from_score
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.portfolio import Holding


def _decision(symbol, **kw) -> HoldingDecision:
    score = kw.get("overall_score", 75)
    defaults = dict(
        name=symbol, current_price=1000.0, overall_score=75, overall_stars=stars_from_score(score),
        action="買い増し", fair_value=1080.0, discount_pct=-8.0, risk_reward=2.0,
        supply_demand_stars="★★★☆☆", dividend_stars="★★★☆☆", dividend_yield=3.0,
        days_to_earnings=None, earnings_alert=False,
        expected_returns=[HorizonExpectation("半年〜1年", 12.0, "★★★", "中", "モデル推定", "r")],
        comment="c", volatility_pct=2.0, sector="Industrials", reasons=["割安圏"],
    )
    defaults.update(kw)
    return HoldingDecision(symbol=symbol, **defaults)


def _run(holdings, decisions_by_symbol):
    scores = {s: d.overall_score for s, d in decisions_by_symbol.items()}
    with patch("stock_analyzer.cli.fetch_market_snapshot", return_value={"日経平均": (39000.0, -1.5), "TOPIX": (2700.0, -1.2)}), \
         patch("stock_analyzer.cli.evaluate_market_sentiment", return_value="弱気"), \
         patch("stock_analyzer.cli._benchmark_context", return_value=(None, None)), \
         patch("stock_analyzer.cli.load_stats", return_value=None), \
         patch("stock_analyzer.cli.load_strategy_stats", return_value=None), \
         patch("stock_analyzer.cli.current_market_regime", return_value="下落"), \
         patch("stock_analyzer.cli._analyze_with_retry", side_effect=lambda h: h), \
         patch("stock_analyzer.cli._enriched_summary",
               side_effect=lambda analysis, *a, **k: SimpleNamespace(
                   symbol=analysis.symbol, raw_score=scores.get(analysis.symbol, 50))), \
         patch("stock_analyzer.cli._decision_from",
               side_effect=lambda summary, analysis, backtest: decisions_by_symbol[analysis.symbol]), \
         patch("stock_analyzer.cli.prescreen_symbols", return_value=[]):
        return collect_report_data(holdings, include_swing_pick=False)


def test_healthy_portfolio_has_zero_violations():
    decisions = {
        "7203.T": _decision("7203.T", overall_score=78, action="買い増し", discount_pct=-6.0),
        "6758.T": _decision("6758.T", overall_score=64, action="保有", discount_pct=-2.0),
        "8306.T": _decision("8306.T", overall_score=50, action="様子見", discount_pct=3.0),
    }
    data = _run(
        [Holding("7203.T", 10, 900.0), Holding("6758.T", 5, 1000.0), Holding("8306.T", 8, 1100.0)],
        decisions,
    )
    assert data.violations == [], [f"{v.rule}:{v.detail}" for v in data.violations]


def test_overvalued_strong_buy_is_self_healed():
    # 割高(+20%)なのに「強く買い増し」95点 という矛盾入力 → 改修ループで解消される想定
    bad = _decision("9999.T", overall_score=95, overall_stars="★★★★★",
                    action="強く買い増し", discount_pct=20.0, fair_value=830.0)
    data = _run([Holding("9999.T", 10, 800.0)], {"9999.T": bad})
    healed = {d.symbol: d for d in data.decisions}["9999.T"]
    assert healed.action != "強く買い増し"
    assert healed.overall_score <= 80
    # 最終整合チェックでも割高強気の違反は残らない
    assert not any(v.rule == "2.割高強気" for v in data.violations)


def test_overweight_neutral_card_is_reconciled_to_trim():
    # [カテゴリ10 再発] 保有比率が過大な「保有(現状維持)」カードは、リバランスの縮小指示と
    # 矛盾しないよう「一部売却(サイズ調整)」へ整合され、方向矛盾の違反が0になる。
    big = _decision("BIG.T", overall_score=82, action="保有", discount_pct=-4.0)
    big.current_price = 5000.0  # 大きな評価額でポートを占有
    small = _decision("SML.T", overall_score=60, action="様子見", discount_pct=1.0)
    small.current_price = 500.0
    data = _run([Holding("BIG.T", 100, 4000.0), Holding("SML.T", 10, 480.0)],
                {"BIG.T": big, "SML.T": small})
    result = {d.symbol: d for d in data.decisions}["BIG.T"]
    # ポート最適化に合わせサイズ調整(一部売却)へ整合
    assert result.action == "一部売却"
    assert result.sizing_trim is True
    # 方向矛盾(check #1)を含め、最終整合チェックは違反0
    assert data.violations == [], [f"{v.rule}:{v.detail}" for v in data.violations]


def test_bearish_market_raises_cash_range():
    # 市場「弱気」→ 現金レンジ15-25%(スタンス連動)
    d = _decision("7203.T", overall_score=78, action="買い増し", discount_pct=-6.0)
    data = _run([Holding("7203.T", 10, 900.0)], {"7203.T": d})
    assert data.allocation.cash_range == (15.0, 25.0)
    assert data.allocation.stance == "弱気"
