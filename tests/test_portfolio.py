from unittest.mock import MagicMock, patch

from stock_analyzer.portfolio import (
    load_portfolio,
    load_portfolio_from_sheet,
    normalize_account,
    normalize_symbol,
    parse_amount,
)


def test_parse_amount_handles_blanks_and_separators():
    assert parse_amount("100") == 100.0
    assert parse_amount("1,000") == 1000.0
    assert parse_amount(" 3000 ") == 3000.0
    assert parse_amount("") is None
    assert parse_amount(None) is None
    assert parse_amount("abc") is None


def test_load_portfolio_blank_quantity_becomes_watch(tmp_path):
    # 数量未入力の行は「監視銘柄」(未保有・数量0)として読み込み、分析対象に含める
    csv_path = tmp_path / "portfolio.csv"
    csv_path.write_text(
        "symbol,quantity,avg_cost,name\n"
        "7203.T,100,3000,トヨタ\n"
        "6758.T,,,ソニー\n"  # 数量・単価 空欄 → 監視銘柄
        "9432.T,,4000,NTT\n",  # 数量 空欄 → 監視銘柄
        encoding="utf-8",
    )
    holdings = load_portfolio(str(csv_path))
    assert [h.symbol for h in holdings] == ["7203.T", "6758.T", "9432.T"]
    held = {h.symbol: h for h in holdings}
    assert held["7203.T"].is_watch is False
    assert held["6758.T"].is_watch is True
    assert held["6758.T"].quantity == 0.0
    assert held["9432.T"].is_watch is True  # 単価だけ入れても数量が無ければ監視


def test_load_portfolio_from_sheet_blank_quantity_becomes_watch():
    from unittest.mock import MagicMock, patch

    mock_worksheet = MagicMock()
    mock_worksheet.get_all_records.return_value = [
        {"symbol": "7203.T", "quantity": "100", "avg_cost": "3000"},
        {"symbol": "6758.T", "quantity": "", "avg_cost": ""},  # 監視銘柄
    ]
    mock_client = MagicMock()
    mock_client.open_by_key.return_value.sheet1 = mock_worksheet

    with patch(
        "stock_analyzer.portfolio.gspread.service_account_from_dict",
        return_value=mock_client,
    ):
        holdings = load_portfolio_from_sheet("dummy-sheet-id", {"fake": "creds"})

    assert [h.symbol for h in holdings] == ["7203.T", "6758.T"]
    assert holdings[1].is_watch is True


def test_normalize_account_variants():
    assert normalize_account("NISA") == "NISA"
    assert normalize_account("nisa") == "NISA"
    assert normalize_account("成長投資枠") == "NISA"
    assert normalize_account("つみたてNISA") == "NISA"
    assert normalize_account("特定") == "特定"
    assert normalize_account("一般") == "特定"
    assert normalize_account("") == "特定"
    assert normalize_account(None) == "特定"


def test_load_portfolio_reads_account_column(tmp_path):
    csv_path = tmp_path / "portfolio.csv"
    csv_path.write_text(
        "symbol,quantity,avg_cost,account\n"
        "7203.T,100,3000,NISA\n"
        "6758.T,10,13000,特定\n"
        "9432.T,10,4000,\n",
        encoding="utf-8",
    )

    holdings = load_portfolio(str(csv_path))

    assert holdings[0].account == "NISA"
    assert holdings[1].account == "特定"
    assert holdings[2].account == "特定"  # 未指定は特定扱い


def test_load_portfolio_defaults_account_when_column_absent(tmp_path):
    csv_path = tmp_path / "portfolio.csv"
    csv_path.write_text(
        "symbol,quantity,avg_cost\n7203.T,100,3000\n",
        encoding="utf-8",
    )
    holdings = load_portfolio(str(csv_path))
    assert holdings[0].account == "特定"


def test_normalize_symbol_appends_t_for_numeric_japanese_codes():
    assert normalize_symbol("7203") == "7203.T"
    assert normalize_symbol(" 6758 ") == "6758.T"
    assert normalize_symbol("142a") == "142A.T"


def test_normalize_symbol_leaves_us_tickers_and_existing_suffix():
    assert normalize_symbol("aapl") == "AAPL"
    assert normalize_symbol("7203.T") == "7203.T"


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
    assert holdings[0].name is None
    assert holdings[1].symbol == "MSFT"


def test_load_portfolio_reads_optional_name_column(tmp_path):
    csv_path = tmp_path / "portfolio.csv"
    csv_path.write_text(
        "symbol,quantity,avg_cost,name\n"
        "7203.T,100,3000,トヨタ自動車\n"
        "6758.T,10,13000,\n",
        encoding="utf-8",
    )

    holdings = load_portfolio(str(csv_path))

    assert holdings[0].name == "トヨタ自動車"
    assert holdings[1].name is None


def test_load_portfolio_auto_appends_t_suffix(tmp_path):
    csv_path = tmp_path / "portfolio.csv"
    csv_path.write_text(
        "symbol,quantity,avg_cost\n7203,100,3000\nAAPL,10,150\n",
        encoding="utf-8",
    )

    holdings = load_portfolio(str(csv_path))

    assert holdings[0].symbol == "7203.T"
    assert holdings[1].symbol == "AAPL"


def test_load_portfolio_from_sheet_parses_rows():
    mock_worksheet = MagicMock()
    mock_worksheet.get_all_records.return_value = [
        {"symbol": "aapl", "quantity": "10", "avg_cost": "150.5", "name": "アップル"},
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
    assert holdings[0].name == "アップル"
    assert holdings[1].symbol == "MSFT"
    assert holdings[1].name is None


def test_load_portfolio_from_sheet_skips_blank_rows():
    mock_worksheet = MagicMock()
    mock_worksheet.get_all_records.return_value = [
        {"symbol": "AAPL", "quantity": "10", "avg_cost": "150.5"},
        {"symbol": "", "quantity": "", "avg_cost": ""},
    ]
    mock_client = MagicMock()
    mock_client.open_by_key.return_value.sheet1 = mock_worksheet

    with patch(
        "stock_analyzer.portfolio.gspread.service_account_from_dict",
        return_value=mock_client,
    ):
        holdings = load_portfolio_from_sheet("dummy-sheet-id", {"fake": "creds"})

    assert len(holdings) == 1
    assert holdings[0].symbol == "AAPL"
