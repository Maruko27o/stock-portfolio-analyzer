from unittest.mock import patch

import pytest

from stock_analyzer.cli import generate_flex_messages
from stock_analyzer.portfolio import Holding
from stock_analyzer.summary import HoldingSummary


def _summary(symbol, raw_score):
    return HoldingSummary(
        symbol=symbol,
        name=None,
        current_price=100.0,
        avg_cost=90.0,
        profit_pct=11.1,
        score=min(raw_score, 100),
        raw_score=raw_score,
        rating="○",
        action="保有継続",
        take_profit=110.0,
        stop_loss=85.0,
        add_price=None,
        reasons=["r"],
        risks=[],
    )


def test_generate_flex_skips_failed_holdings_and_notes_them():
    holdings = [Holding("AAA", 1, 100), Holding("BBB", 1, 100)]

    def fake_analyze(holding):
        if holding.symbol == "BBB":
            raise RuntimeError("rate limited")
        return holding  # placeholder; build_summary is patched

    with patch("stock_analyzer.cli.time.sleep"), patch(
        "stock_analyzer.cli.fetch_market_snapshot", return_value={"日経平均": (1.0, 1.0)}
    ), patch("stock_analyzer.cli.evaluate_market_sentiment", return_value="強気"), patch(
        "stock_analyzer.cli._benchmark_context", return_value=(None, None)
    ), patch(
        "stock_analyzer.cli.analyze_holding", side_effect=fake_analyze
    ), patch(
        "stock_analyzer.cli.build_summary",
        side_effect=lambda a, s, *rest: _summary(a.symbol, 60),
    ), patch("stock_analyzer.cli.top_swing_picks", return_value=[]):
        messages = generate_flex_messages(holdings)

    text_notes = [m for m in messages if m.get("type") == "text"]
    assert any("BBB" in m["text"] for m in text_notes)
    # The market card + the one successful holding still produce a flex message.
    assert any(m.get("type") == "flex" for m in messages)


def test_generate_flex_survives_market_failure():
    holdings = [Holding("AAA", 1, 100)]

    with patch("stock_analyzer.cli.fetch_market_snapshot", side_effect=RuntimeError("boom")), patch(
        "stock_analyzer.cli._benchmark_context", return_value=(None, None)
    ), patch(
        "stock_analyzer.cli.analyze_holding", side_effect=lambda h: h
    ), patch(
        "stock_analyzer.cli.build_summary",
        side_effect=lambda a, s, *rest: _summary(a.symbol, 60),
    ), patch("stock_analyzer.cli.top_swing_picks", return_value=[]):
        messages = generate_flex_messages(holdings)

    assert any(m.get("type") == "flex" for m in messages)


def test_generate_flex_raises_when_everything_fails():
    holdings = [Holding("AAA", 1, 100)]

    with patch("stock_analyzer.cli.time.sleep"), patch(
        "stock_analyzer.cli.fetch_market_snapshot", side_effect=RuntimeError("boom")
    ), patch("stock_analyzer.cli._benchmark_context", return_value=(None, None)), patch(
        "stock_analyzer.cli.analyze_holding", side_effect=RuntimeError("rate limited")
    ), patch(
        "stock_analyzer.cli.top_swing_picks", return_value=[]
    ):
        with pytest.raises(RuntimeError):
            generate_flex_messages(holdings)
