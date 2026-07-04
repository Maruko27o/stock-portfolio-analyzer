from __future__ import annotations

import argparse
import os
import sys

from stock_analyzer.cli import generate_report
from stock_analyzer.notifier import send_line_broadcast
from stock_analyzer.portfolio import load_portfolio

LINE_TOKEN_ENV_VAR = "LINE_CHANNEL_ACCESS_TOKEN"


def main() -> None:
    parser = argparse.ArgumentParser(description="保有銘柄の分析レポートをLINEに通知します")
    parser.add_argument("--portfolio", required=True, help="保有銘柄CSVのパス")
    args = parser.parse_args()

    token = os.environ.get(LINE_TOKEN_ENV_VAR)
    if not token:
        print(f"{LINE_TOKEN_ENV_VAR} が設定されていません", file=sys.stderr)
        raise SystemExit(1)

    holdings = load_portfolio(args.portfolio)
    message = "\n".join(generate_report(holdings))

    send_line_broadcast(message, token)
    print("LINEへの通知を送信しました")


if __name__ == "__main__":
    main()
