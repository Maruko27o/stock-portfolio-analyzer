from unittest.mock import MagicMock, patch

from stock_analyzer.portfolio import load_portfolio, load_portfolio_from_sheet


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


def test_load_portfolio_from_sheet_parses_rows():
    mock_worksheet = MagicMock()
    mock_worksheet.get_all_records.return_value = [
        {"symbol": "aapl", "quantity": "10", "avg_cost": "150.5"},
        {"symbol": "MSFT", "quantity": "5", "avg_cost": "300"},
    ]
    mock_client = MagicMock()
    mock_client.open_by_key.return_value.sheet1 = mock_worksheet

    with patch(
        "stock_analyzer.portfolio.gspread.service_account_from_dict",
        return_value=mock_client,
    ):
        holdings = load_portfolio_from_sheet("dummy-sheet-id", {"fake": "creds"})

    assert len(holdings) == 2
    assert holdings[0].symbol == "AAPL"
    assert holdings[0].quantity == 10
    assert holdings[0].avg_cost == 150.5
    assert holdings[1].symbol == "MSFT"
