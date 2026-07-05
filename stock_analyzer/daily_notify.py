from __future__ import annotations

import argparse
import json
import os
import sys

from stock_analyzer.cli import collect_report_data, discord_embeds_from, flex_messages_from
from stock_analyzer.discord import send_discord
from stock_analyzer.notifier import broadcast_messages
from stock_analyzer.portfolio import Holding, load_portfolio, load_portfolio_from_sheet

LINE_TOKEN_ENV_VAR = "LINE_CHANNEL_ACCESS_TOKEN"
DISCORD_WEBHOOK_ENV_VAR = "DISCORD_WEBHOOK_URL"
GOOGLE_SERVICE_ACCOUNT_ENV_VAR = "GOOGLE_SERVICE_ACCOUNT_JSON"
GOOGLE_SHEET_ID_ENV_VAR = "GOOGLE_SHEET_ID"


def load_holdings(portfolio_path: str | None) -> list[Holding]:
    """Load holdings from the Google Sheet if configured, else fall back to a CSV path."""
    sheet_id = os.environ.get(GOOGLE_SHEET_ID_ENV_VAR)
    service_account_json = os.environ.get(GOOGLE_SERVICE_ACCOUNT_ENV_VAR)

    if sheet_id and service_account_json:
        return load_portfolio_from_sheet(sheet_id, json.loads(service_account_json))

    if portfolio_path:
        return load_portfolio(portfolio_path)

    print(
        f"保有銘柄の取得元がありません: {GOOGLE_SHEET_ID_ENV_VAR}/{GOOGLE_SERVICE_ACCOUNT_ENV_VAR} "
        "を設定するか --portfolio を指定してください",
        file=sys.stderr,
    )
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="保有銘柄の分析レポートを通知します")
    parser.add_argument(
        "--portfolio", help="保有銘柄CSVのパス(Googleスプレッドシート未設定時のフォールバック)"
    )
    args = parser.parse_args()

    line_token = os.environ.get(LINE_TOKEN_ENV_VAR)
    discord_url = os.environ.get(DISCORD_WEBHOOK_ENV_VAR)
    if not line_token and not discord_url:
        print(
            f"通知先が設定されていません（{LINE_TOKEN_ENV_VAR} または {DISCORD_WEBHOOK_ENV_VAR}）",
            file=sys.stderr,
        )
        raise SystemExit(1)

    holdings = load_holdings(args.portfolio)
    data = collect_report_data(holdings)  # fetched once, rendered per channel

    if discord_url:
        send_discord(discord_url, discord_embeds_from(data))
        print("Discordへの通知を送信しました")
    if line_token:
        broadcast_messages(flex_messages_from(data), line_token)
        print("LINEへの通知を送信しました")


if __name__ == "__main__":
    main()
