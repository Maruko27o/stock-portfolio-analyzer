from __future__ import annotations

import csv
import sys
from dataclasses import dataclass

import gspread


@dataclass
class Holding:
    symbol: str
    quantity: float
    avg_cost: float
    name: str | None = None
    account: str = "特定"  # "NISA" | "特定"。税最適化(tax.py)で口座別に扱う


def _row_name(row: dict) -> str | None:
    """Return the optional 'name' column value, or None if absent/blank."""
    name = str(row.get("name", "") or "").strip()
    return name or None


def normalize_account(raw: str | None) -> str:
    """口座区分の表記ゆれを "NISA" / "特定" の2値へ寄せる。

    NISA(新旧・つみたて・成長投資枠)は非課税で税最適化の扱いが異なるため区別する。
    それ以外(特定/一般/未指定)は課税口座として "特定" にまとめる。
    """
    text = str(raw or "").strip()
    if not text:
        return "特定"
    lowered = text.lower()
    if "nisa" in lowered or "ニーサ" in text or "成長投資" in text or "つみたて" in text:
        return "NISA"
    return "特定"


def parse_amount(value) -> float | None:
    """数量・取得単価のセルを数値化する。空欄や数値でない場合は None を返す。

    スプレッドシートは編集途中で数量/単価が未入力のことがある。そこで例外にせず
    None を返し、呼び出し側で「未完成の行」としてスキップできるようにする。
    カンマ区切り(例: "1,000")や全角スペースも許容する。
    """
    text = str(value if value is not None else "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _warn_skipped(skipped: list[str]) -> None:
    if skipped:
        print(
            "保有の数量/取得単価が未入力のためスキップした銘柄: " + ", ".join(skipped),
            file=sys.stderr,
        )


def normalize_symbol(raw: str) -> str:
    """Normalize a ticker, auto-appending the Tokyo '.T' suffix for Japanese codes.

    Japanese stock codes contain digits (e.g. '7203', or newer alphanumeric like
    '142A') and get '.T' added so the user can omit it. Tickers that already have a
    suffix ('7203.T') or are purely alphabetic ('AAPL') are left unchanged.
    """
    symbol = raw.strip().upper()
    if symbol and "." not in symbol and any(ch.isdigit() for ch in symbol):
        symbol += ".T"
    return symbol


def load_portfolio(path: str) -> list[Holding]:
    """Load holdings from a CSV file with columns: symbol,quantity,avg_cost[,name]."""
    holdings: list[Holding] = []
    skipped: list[str] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = str(row.get("symbol", "") or "").strip()
            if not symbol:
                continue
            quantity = parse_amount(row.get("quantity"))
            avg_cost = parse_amount(row.get("avg_cost"))
            if quantity is None or avg_cost is None:
                skipped.append(symbol)  # 数量/単価が未入力の行は飛ばす(通知は落とさない)
                continue
            holdings.append(
                Holding(
                    symbol=normalize_symbol(symbol),
                    quantity=quantity,
                    avg_cost=avg_cost,
                    name=_row_name(row),
                    account=normalize_account(row.get("account")),
                )
            )
    _warn_skipped(skipped)
    return holdings


def load_portfolio_from_sheet(sheet_id: str, service_account_info: dict) -> list[Holding]:
    """Load holdings from a private Google Sheet (columns: symbol, quantity, avg_cost[, name]).

    `service_account_info` is the parsed JSON key of a Google service account
    that has been granted read access to the sheet; the sheet is not public.
    The optional `name` column lets you set a custom (e.g. Japanese) display name.
    """
    client = gspread.service_account_from_dict(service_account_info)
    worksheet = client.open_by_key(sheet_id).sheet1

    holdings: list[Holding] = []
    skipped: list[str] = []
    for row in worksheet.get_all_records():
        symbol = str(row.get("symbol", "")).strip()
        if not symbol:
            continue
        quantity = parse_amount(row.get("quantity"))
        avg_cost = parse_amount(row.get("avg_cost"))
        if quantity is None or avg_cost is None:
            skipped.append(symbol)  # 数量/単価が未入力の行は飛ばす(通知は落とさない)
            continue
        holdings.append(
            Holding(
                symbol=normalize_symbol(symbol),
                quantity=quantity,
                avg_cost=avg_cost,
                name=_row_name(row),
                account=normalize_account(row.get("account")),
            )
        )
    _warn_skipped(skipped)
    return holdings
