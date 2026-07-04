from stock_analyzer.portfolio import load_portfolio


def test_load_portfolio_parses_csv_rows(tmp_path):
    csv_path = tmp_path / "portfolio.csv"
    csv_path.write_text(
        "symbol,quantity,avg_cost\n"
        "aapl,10,150.5\n"
        "MSFT,5,300\n",
        encoding="utf-8",
    )

    holdings = load_portfolio(str(csv_path))

    assert len(holdings) == 2
    assert holdings[0].symbol == "AAPL"
    assert holdings[0].quantity == 10
    assert holdings[0].avg_cost == 150.5
    assert holdings[1].symbol == "MSFT"
