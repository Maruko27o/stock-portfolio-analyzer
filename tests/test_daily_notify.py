from stock_analyzer.daily_notify import holdings_from_symbols


def test_holdings_from_symbols_normalizes_and_marks_watch_only():
    holdings = holdings_from_symbols("7203, 6758")
    assert [h.symbol for h in holdings] == ["7203.T", "6758.T"]
    assert all(h.quantity == 0 and h.avg_cost == 0.0 for h in holdings)


def test_holdings_from_symbols_accepts_spaces_and_japanese_commas():
    holdings = holdings_from_symbols(" 7203　6758、AAPL ")
    assert [h.symbol for h in holdings] == ["7203.T", "6758.T", "AAPL"]


def test_holdings_from_symbols_keeps_existing_suffix():
    assert holdings_from_symbols("9984.T")[0].symbol == "9984.T"


def test_holdings_from_symbols_empty_text_gives_no_holdings():
    assert holdings_from_symbols("") == []
    assert holdings_from_symbols("  ,  ") == []
