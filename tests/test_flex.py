from stock_analyzer.flex import (
    RATING_COLOR,
    holding_bubble,
    market_bubble,
    swing_bubble,
    to_flex_messages,
)
from stock_analyzer.summary import HoldingSummary


def _summary(**overrides) -> HoldingSummary:
    defaults = dict(
        symbol="7203.T",
        name="トヨタ自動車",
        current_price=3500.0,
        avg_cost=3000.0,
        profit_pct=16.7,
        score=88,
        raw_score=95,
        rating="◎◎",
        action="保有継続",
        take_profit=3700.0,
        stop_loss=3360.0,
        add_price=3400.0,
        reasons=["25日線を上抜け", "MACDゴールデンクロス"],
        risks=["決算まであと3日"],
    )
    defaults.update(overrides)
    return HoldingSummary(**defaults)


def test_holding_bubble_uses_rating_color_and_contains_heading():
    bubble = holding_bubble(_summary())
    assert bubble["type"] == "bubble"
    assert bubble["header"]["backgroundColor"] == RATING_COLOR["◎◎"]
    header_texts = [c["text"] for c in bubble["header"]["contents"]]
    assert any("7203.T トヨタ自動車" in t for t in header_texts)


def test_holding_bubble_includes_risks_section_when_present():
    bubble = holding_bubble(_summary())
    body_texts = [c.get("text", "") for c in bubble["body"]["contents"]]
    assert any("注意点" in t for t in body_texts)


def test_holding_bubble_hides_cost_rows_for_watch_only_symbols():
    bubble = holding_bubble(_summary(avg_cost=0.0, profit_pct=None))
    body = bubble["body"]["contents"]
    labels = [
        row["contents"][0]["text"]
        for row in body
        if row.get("type") == "box" and row.get("layout") == "horizontal"
    ]
    assert "現在" in labels
    assert "取得" not in labels
    assert "損益" not in labels


def test_holding_bubble_always_shows_dividend_rows():
    from datetime import date

    bubble = holding_bubble(
        _summary(
            dividend_yield=4.24,
            yield_on_cost=4.87,
            ex_dividend_date=date(2026, 7, 30),
            days_to_ex_dividend=25,
        )
    )
    rows = [
        (row["contents"][0]["text"], row["contents"][1]["text"])
        for row in bubble["body"]["contents"]
        if row.get("type") == "box" and row.get("layout") == "horizontal"
    ]
    assert ("配当", "4.24%(取得比4.87%)") in rows
    assert ("権利落ち", "2026/7/30(あと25日)") in rows

    # Shown even when data is missing, so the user always sees the slot.
    bare = holding_bubble(_summary())
    labels = [
        row["contents"][0]["text"]
        for row in bare["body"]["contents"]
        if row.get("type") == "box" and row.get("layout") == "horizontal"
    ]
    assert "配当" in labels
    assert "権利落ち" in labels


def test_market_bubble_lists_indices():
    snapshot = {"日経平均": (39000.0, 1.2), "ドル円": (150.0, -0.3)}
    bubble = market_bubble("強気", snapshot)
    assert bubble["type"] == "bubble"
    # header shows the sentiment
    assert any(c["text"] == "強気" for c in bubble["header"]["contents"])


def test_swing_bubble_numbers_the_picks():
    picks = [
        {"heading": "1721.T A", "score": 100, "current_price": 5000.0, "reasons": ["r1"]},
        {"heading": "1812.T B", "score": 98, "current_price": 6000.0, "reasons": ["r2"]},
    ]
    bubble = swing_bubble(picks)
    body_texts = [c.get("text", "") for c in bubble["body"]["contents"]]
    assert any(t.startswith("1. 1721.T A") for t in body_texts)
    assert any(t.startswith("2. 1812.T B") for t in body_texts)


def test_to_flex_messages_splits_into_carousels_of_ten():
    bubbles = [{"type": "bubble", "body": {}} for _ in range(23)]
    messages = to_flex_messages(bubbles, alt_text="x")
    assert len(messages) == 3  # 10 + 10 + 3
    assert all(m["type"] == "flex" for m in messages)
    assert len(messages[0]["contents"]["contents"]) == 10
    assert len(messages[2]["contents"]["contents"]) == 3
