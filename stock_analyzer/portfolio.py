from __future__ import annotations

import csv
from dataclasses import dataclass


@dataclass
class Holding:
    symbol: str
    quantity: float
    avg_cost: float


def load_portfolio(path: str) -> list[Holding]:
    """Load holdings from a CSV file with columns: symbol,quantity,avg_cost."""
    holdings = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            holdings.append(
                Holding(
                    symbol=row["symbol"].strip().upper(),
                    quantity=float(row["quantity"]),
                    avg_cost=float(row["avg_cost"]),
                )
            )
    return holdings
