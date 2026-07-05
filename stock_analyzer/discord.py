from __future__ import annotations

import time

import requests

from stock_analyzer.flex import RATING_COLOR, SENTIMENT_COLOR
from stock_analyzer.market import vix_regime_label
from stock_analyzer.summary import (
    RATING_EMOJI,
    RATING_LABEL,
    HoldingSummary,
    format_as_of,
    format_dividend_yield,
    format_ex_dividend,
)

MAX_EMBEDS_PER_MESSAGE = 10


def _color_int(hex_color: str) -> int:
    return int(hex_color.lstrip("#"), 16)


def _price(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.0f}円"
    return f"{value:,.2f}"


def market_embed(
    sentiment: str,
    snapshot: dict[str, tuple[float | None, float | None]],
    as_of=None,
) -> dict:
    lines = []
    for name, (price, change) in snapshot.items():
        if name == "VIX":
            vix_text = f"{price:.1f}({vix_regime_label(price)})" if price is not None else "—"
            lines.append(f"{name}: {vix_text}")
            continue
        change_text = f"{change:+.2f}%" if change is not None else "—"
        lines.append(f"{name}: {change_text}")
    as_of_note = format_as_of(as_of)
    if as_of_note:
        lines.append(as_of_note)
    return {
        "title": f"📊 本日の市場：{sentiment}",
        "description": "\n".join(lines),
        "color": _color_int(SENTIMENT_COLOR.get(sentiment, "#7F8C8D")),
    }


def holding_embed(summary: HoldingSummary) -> dict:
    heading = f"{summary.symbol} {summary.name}" if summary.name else summary.symbol
    profit = f"{summary.profit_pct:+.1f}%" if summary.profit_pct is not None else "—"

    if summary.avg_cost > 0:
        position_line = (
            f"現在: {_price(summary.current_price)} / 取得: {_price(summary.avg_cost)} / 損益: {profit}"
        )
    else:
        # Watch-only symbols (on-demand analysis) have no position, so skip 取得/損益.
        position_line = f"現在: {_price(summary.current_price)}"
    dividend_line = (
        f"配当: {format_dividend_yield(summary.dividend_yield, summary.yield_on_cost)}"
        f" / 権利落ち: "
        f"{format_ex_dividend(summary.ex_dividend_date, summary.days_to_ex_dividend, summary.ex_dividend_estimated)}"
    )
    parts = [
        position_line,
        dividend_line,
        f"**判断**: {summary.action}",
        f"第一目標: {_price(summary.take_profit)} / 損切: {_price(summary.stop_loss)}"
        + (f" / 押し目: {_price(summary.add_price)}" if summary.add_price is not None else ""),
    ]
    if summary.backtest:
        from stock_analyzer.backtest_stats import format_backtest_compact

        parts.append(f"**{format_backtest_compact(summary.backtest)}**")
    if summary.reasons:
        parts.append("**判断理由**\n" + "\n".join(f"・{r}" for r in summary.reasons))
    if summary.risks:
        parts.append("**注意点**\n" + "\n".join(f"・{r}" for r in summary.risks))

    return {
        "title": f"{RATING_EMOJI[summary.rating]} {heading} — {summary.rating} {summary.score}点"
        f"（{RATING_LABEL[summary.rating]}）",
        "description": "\n".join(parts),
        "color": _color_int(RATING_COLOR[summary.rating]),
    }


def swing_embed(picks: list[dict]) -> dict:
    blocks = []
    for index, pick in enumerate(picks, start=1):
        reasons = "\n".join(f"・{r}" for r in pick["reasons"])
        blocks.append(
            f"**{index}. {pick['heading']}　{pick['score']}点**\n"
            f"現在: {_price(pick['current_price'])}\n{reasons}"
        )
    disclaimer = "※保有していない銘柄です。機械的スコアによる候補で、値上がりを保証するものではありません。"
    return {
        "title": "🔎 注目候補（スイング）TOP3",
        "description": "\n\n".join(blocks) + "\n\n" + disclaimer,
        "color": _color_int("#16A085"),
    }


def failed_embed(symbols: list[str]) -> dict:
    return {
        "title": "⚠️ 取得できなかった銘柄",
        "description": ", ".join(symbols),
        "color": _color_int("#B7950B"),
    }


def send_discord(webhook_url: str, embeds: list[dict]) -> None:
    """Post embeds to a Discord webhook, max 10 per message, honoring rate limits."""
    for start in range(0, len(embeds), MAX_EMBEDS_PER_MESSAGE):
        batch = embeds[start : start + MAX_EMBEDS_PER_MESSAGE]
        for attempt in range(2):
            response = requests.post(webhook_url, json={"embeds": batch}, timeout=10)
            if response.status_code == 429 and attempt == 0:
                retry_after = response.json().get("retry_after", 1)
                time.sleep(float(retry_after))
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"Discord webhook error {response.status_code}: {response.text}")
            break
