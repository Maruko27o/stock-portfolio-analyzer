from __future__ import annotations

import csv
from dataclasses import dataclass

import gspread


@dataclass
class Holding:
    symbol: str
    quantity: float
    avg_cost: float
    name: str | None = None


def _row_name(row: dict) -> str | None:
    """Return the optional 'name' column value, or None if absent/blank."""
    name = str(row.get("name", "") or "").strip()
    return name or None


def load_portfolio(path: str) -> list[Holding]:
    """Load holdings from a CSV file with columns: symbol,quantity,avg_cost[,name]."""
    holdings = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            holdings.append(
                Holding(
                    symbol=row["symbol"].strip().upper(),
                    quantity=float(row["quantity"]),
                    avg_cost=float(row["avg_cost"]),
                    name=_row_name(row),
                )
            )
    return holdings


def load_portfolio_from_sheet(sheet_id: str, service_account_info: dict) -> list[Holding]:
    """Load holdings from a private Google Sheet (columns: symbol, quantity, avg_cost[, name]).

    `service_account_info` is the parsed JSON key of a Google service account
    that has been granted read access to the sheet; the sheet is not public.
    The optional `name` column lets you set a custom (e.g. Japanese) display name.
    """
    client = gspread.service_account_from_dict(service_account_info)
    worksheet = client.open_by_key(sheet_id).sheet1

    holdings = []
    for row in worksheet.get_all_records():
        symbol = str(row.get("symbol", "")).strip()
        if not symbol:
            continue
        holdings.append(
            Holding(
                symbol=symbol.upper(),
                quantity=float(row["quantity"]),
                avg_cost=float(row["avg_cost"]),
                name=_row_name(row),
            )
        )
    return holdings
