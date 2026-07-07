from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_analyzer.cli import (
    collect_report_data,
    discord_embeds_from,
    flex_messages_from,
    render_summary_text,
)
from stock_analyzer.discord import send_discord
from stock_analyzer.review import llm_review
from stock_analyzer.judgment_log import append_judgments
from stock_analyzer.market_calendar import is_market_closed
from stock_analyzer.notifier import broadcast_messages
from stock_analyzer.portfolio import (
    Holding,
    load_portfolio,
    load_portfolio_from_sheet,
    normalize_symbol,
)

LINE_TOKEN_ENV_VAR = "LINE_CHANNEL_ACCESS_TOKEN"
DISCORD_WEBHOOK_ENV_VAR = "DISCORD_WEBHOOK_URL"
GOOGLE_SERVICE_ACCOUNT_ENV_VAR = "GOOGLE_SERVICE_ACCOUNT_JSON"
GOOGLE_SHEET_ID_ENV_VAR = "GOOGLE_SHEET_ID"
ANALYZE_SYMBOLS_ENV_VAR = "ANALYZE_SYMBOLS"
SKIP_IF_CLOSED_ENV_VAR = "SKIP_IF_MARKET_CLOSED"
JUDGMENT_LOG_ENV_VAR = "JUDGMENT_LOG"


def holdings_from_symbols(text: str) -> list[Holding]:
    """Parse 'symbols' input ('7203, 6758' etc.) into watch-only holdings (no position)."""
    symbols = [normalize_symbol(part) for part in re.split(r"[\s,、]+", text) if part.strip()]
    return [Holding(symbol=symbol, quantity=0, avg_cost=0.0) for symbol in symbols]


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
    parser.add_argument(
        "--symbols", help="指定した銘柄だけをオンデマンド分析(カンマ区切り。例: 7203,6758)"
    )
    args = parser.parse_args()

    symbols_text = args.symbols or os.environ.get(ANALYZE_SYMBOLS_ENV_VAR, "")

    # Scheduled runs skip closed days. The cron fires every day, so this skip is
    # what keeps weekends, Japanese public holidays, and year-end closures from
    # sending a stale report. On-demand runs (symbols given / manual button) still
    # work on any day.
    if os.environ.get(SKIP_IF_CLOSED_ENV_VAR) and not symbols_text.strip():
        today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
        if is_market_closed(today):
            print(f"市場休場日({today})のため通知をスキップしました")
            return

    line_token = os.environ.get(LINE_TOKEN_ENV_VAR)
    discord_url = os.environ.get(DISCORD_WEBHOOK_ENV_VAR)
    if not line_token and not discord_url:
        print(
            f"通知先が設定されていません（{LINE_TOKEN_ENV_VAR} または {DISCORD_WEBHOOK_ENV_VAR}）",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if symbols_text.strip():
        # On-demand: analyze just the requested tickers (skip the slow universe scan).
        holdings = holdings_from_symbols(symbols_text)
        data = collect_report_data(holdings, include_swing_pick=False)
    else:
        holdings = load_holdings(args.portfolio)
        data = collect_report_data(holdings)  # fetched once, rendered per channel

    if discord_url:
        embeds = discord_embeds_from(data)
        # 任意: ANTHROPIC_API_KEY があれば、Claude によるレビューAIの所見も添える(無ければ無料のまま)。
        review_text = llm_review("\n".join(render_summary_text(data)))
        if review_text:
            embeds.append(
                {"title": "🤖 レビューAI(Claude)", "description": review_text[:4000], "color": 0xE67E22}
            )
            print("レビューAI(Claude)の所見を添付しました")
        send_discord(discord_url, embeds)
        print("Discordへの通知を送信しました")
    if line_token:
        broadcast_messages(flex_messages_from(data), line_token)
        print("LINEへの通知を送信しました")

    # Accumulate score/judgment history so the scoring can be verified against
    # what prices actually did (see verify_log). On-demand watch runs are not
    # logged to keep the record limited to real portfolio judgments.
    log_path = os.environ.get(JUDGMENT_LOG_ENV_VAR)
    if log_path and not symbols_text.strip() and data.summaries:
        append_judgments(log_path, data.summaries)
        print(f"判断ログを追記しました: {log_path}")


if __name__ == "__main__":
    main()
