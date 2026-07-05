from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from stock_analyzer.analysis import HoldingAnalysis, analyze_holding
from stock_analyzer.data_fetcher import (
    fetch_fundamentals,
    fetch_price_history,
    split_confirmed_history,
)
from stock_analyzer.discord import failed_embed, holding_embed, market_embed, swing_embed
from stock_analyzer.fundamentals import (
    evaluate_current_ratio,
    evaluate_debt_to_equity,
    evaluate_dividend_yield,
    evaluate_growth,
    evaluate_payout_ratio,
    evaluate_pbr,
    evaluate_per,
    evaluate_roa,
    evaluate_roe,
)
from stock_analyzer.indicators import (
    evaluate_bollinger,
    evaluate_macd,
    evaluate_price_position,
    rate_of_change,
)
from stock_analyzer.flex import holding_bubble, market_bubble, swing_bubble, to_flex_messages
from stock_analyzer.market import evaluate_market_sentiment, fetch_market_snapshot
from stock_analyzer.portfolio import Holding, load_portfolio
from stock_analyzer.screener import build_swing_section, top_swing_picks
from stock_analyzer.scoring import evaluate_recommendation, total_score
from stock_analyzer.summary import (
    build_summary,
    format_ex_dividend,
    format_market_header,
    format_summary,
)


def _fmt(value: float | None, spec: str = "{:.2f}") -> str:
    return spec.format(value) if value is not None else "データ不足"


def _pct(value: float | None, spec: str = "{:.1f}%") -> str:
    return _fmt(value * 100 if value is not None else None, spec)


def _build_detailed_block(a: HoldingAnalysis) -> list[str]:
    """Render the full, everything-included detailed block for one holding (CLI use)."""
    price_position = (
        evaluate_price_position(a.current_price, a.levels) if a.current_price is not None else "データ不足"
    )
    score = total_score(a.rsi, a.per, a.pbr)
    return [
        f"■ {a.holding.symbol} {a.name or ''}".rstrip()
        + f" ({a.holding.quantity:.0f}株 @{a.holding.avg_cost:.2f})",
        f"現在値: {_fmt(a.current_price)}",
        f"SMA25: {_fmt(a.sma_mid)} / RSI14: {_fmt(a.rsi, '{:.1f}')}",
        f"MACD: {evaluate_macd(a.macd_result)}",
        f"ボリンジャーバンド: {evaluate_bollinger(a.bollinger)}",
        f"出来高: {a.volume_signal}",
        f"出来高トレンド: {_fmt(a.volume_trend_ratio, '{:.2f}倍')} / {a.volume_price_signal}",
        f"価格位置: {price_position}",
        f"52週高値/安値: {_fmt(a.period_high)} / {_fmt(a.period_low)}",
        f"PER: {_fmt(a.per, '{:.1f}')}({evaluate_per(a.per)}) / PBR: {_fmt(a.pbr, '{:.1f}')}({evaluate_pbr(a.pbr)})",
        f"ROE: {_pct(a.roe)}({evaluate_roe(a.roe)}) / ROA: {_pct(a.roa)}({evaluate_roa(a.roa)})",
        f"EPS: {_fmt(a.eps)} / BPS: {_fmt(a.bps)}",
        f"売上成長率: {_pct(a.revenue_growth, '{:+.1f}%')}({evaluate_growth(a.revenue_growth, '増収', '減収')}) "
        f"/ 利益成長率: {_pct(a.earnings_growth, '{:+.1f}%')}({evaluate_growth(a.earnings_growth, '増益', '減益')})",
        f"配当利回り: {_fmt(a.dividend_yield, '{:.2f}%')}({evaluate_dividend_yield(a.dividend_yield)}) "
        f"/ 配当性向: {_pct(a.payout_ratio)}({evaluate_payout_ratio(a.payout_ratio)})",
        f"取得比利回り: {_fmt(a.yield_on_cost, '{:.2f}%')} "
        f"/ 権利落ち日: {format_ex_dividend(a.ex_dividend_date, a.days_to_ex_dividend)}",
        f"負債資本倍率: {_fmt(a.debt_to_equity, '{:.0f}%')}({evaluate_debt_to_equity(a.debt_to_equity)}) "
        f"/ 流動比率: {_fmt(a.current_ratio, '{:.2f}')}({evaluate_current_ratio(a.current_ratio)})",
        f"次回決算日: {a.next_earnings.isoformat() if a.next_earnings else 'データ不足'}"
        + (f" (あと{a.days_to_earnings}日)" if a.days_to_earnings is not None else ""),
        f"セクター: {a.sector or 'データ不足'} / 業種: {a.industry or 'データ不足'}",
        f"総合スコア: {score}/100 ({evaluate_recommendation(score)})",
    ]


def _market_section() -> tuple[str, list[str], dict]:
    """Return (sentiment, detailed market lines, snapshot)."""
    snapshot = fetch_market_snapshot()
    sentiment = evaluate_market_sentiment(snapshot)
    lines = ["【市場環境】", f"市場全体: {sentiment}"]
    for name, (price, change) in snapshot.items():
        lines.append(f"{name}: {_fmt(price)} ({_fmt(change, '{:+.2f}%')})")
    return sentiment, lines, snapshot


def generate_report(holdings: list[Holding]) -> list[str]:
    """Build the full detailed report (all indicators) — used for local CLI inspection."""
    sentiment, market_lines, _ = _market_section()
    lines: list[str] = [*market_lines, ""]
    for holding in holdings:
        lines.extend(_build_detailed_block(analyze_holding(holding)))
        lines.append("")
    return lines


def generate_summary(holdings: list[Holding], include_swing_pick: bool = True) -> list[str]:
    """Build the concise, AI-selected summary report — used for LINE notifications.

    Holdings are ordered by their overall score, highest first.
    """
    sentiment, _, snapshot = _market_section()
    vix = snapshot.get("VIX", (None, None))[0]
    benchmark_momentum = _benchmark_momentum()
    summaries = [
        build_summary(analyze_holding(holding), sentiment, vix, benchmark_momentum)
        for holding in holdings
    ]
    summaries.sort(key=lambda s: s.raw_score, reverse=True)

    lines: list[str] = [format_market_header(sentiment), ""]
    for summary in summaries:
        lines.append(format_summary(summary))
        lines.append("")
    if include_swing_pick:
        lines.extend(build_swing_section())
    return lines


def _analyze_with_retry(holding: Holding, attempts: int = 2, delay: float = 8.0) -> HoldingAnalysis:
    """Analyze a holding, retrying once after a pause to ride out transient rate limits."""
    for attempt in range(attempts):
        try:
            return analyze_holding(holding)
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
    raise RuntimeError("unreachable")


@dataclass
class ReportData:
    """Channel-neutral analysis result, fetched once and rendered to any medium."""

    sentiment: str
    snapshot: dict[str, tuple[float | None, float | None]] | None
    summaries: list  # list[HoldingSummary], ordered by raw_score desc
    swing_picks: list[dict]
    failed_symbols: list[str]

    def is_empty(self) -> bool:
        return not self.snapshot and not self.summaries and not self.swing_picks


BENCHMARK_TICKER = "1306.T"  # TOPIX ETF: baseline to separate stock strength from market tide


def _benchmark_momentum() -> float | None:
    """Return the market benchmark's 10-day rate of change, or None on failure."""
    try:
        confirmed, _ = split_confirmed_history(fetch_price_history(BENCHMARK_TICKER))
        return rate_of_change(confirmed["Close"].tolist(), 10)
    except Exception:
        return None


def collect_report_data(holdings: list[Holding], include_swing_pick: bool = True) -> ReportData:
    """Fetch and compute everything once, tolerating individual failures."""
    snapshot: dict | None = None
    try:
        snapshot = fetch_market_snapshot()
        sentiment = evaluate_market_sentiment(snapshot)
    except Exception:
        sentiment = "中立"  # neutral fallback so holding scores can still be computed

    vix = snapshot.get("VIX", (None, None))[0] if snapshot else None
    benchmark_momentum = _benchmark_momentum()

    summaries = []
    failed_symbols = []
    for holding in holdings:
        try:
            summaries.append(
                build_summary(_analyze_with_retry(holding), sentiment, vix, benchmark_momentum)
            )
        except Exception:
            failed_symbols.append(holding.symbol)
    summaries.sort(key=lambda s: s.raw_score, reverse=True)

    swing_picks: list[dict] = []
    if include_swing_pick:
        try:
            picks = top_swing_picks()
        except Exception:
            picks = []
        for candidate in picks:
            try:
                name = fetch_fundamentals(candidate.symbol)["name"]
            except Exception:
                name = None
            heading = f"{candidate.symbol} {name}" if name else candidate.symbol
            swing_picks.append(
                {
                    "heading": heading,
                    "score": candidate.score,
                    "current_price": candidate.current_price,
                    "reasons": candidate.reasons,
                }
            )

    return ReportData(sentiment, snapshot, summaries, swing_picks, failed_symbols)


def flex_messages_from(data: ReportData) -> list[dict]:
    """Render collected data into LINE Flex message objects."""
    bubbles: list[dict] = []
    if data.snapshot:
        bubbles.append(market_bubble(data.sentiment, data.snapshot))
    bubbles.extend(holding_bubble(summary) for summary in data.summaries)
    if data.swing_picks:
        bubbles.append(swing_bubble(data.swing_picks))

    if not bubbles:
        raise RuntimeError("分析データを取得できませんでした（全銘柄・市場データの取得に失敗）")

    messages = to_flex_messages(bubbles, alt_text="株ポートフォリオ分析")
    if data.failed_symbols:
        messages.append(
            {"type": "text", "text": "⚠️ 取得できなかった銘柄: " + ", ".join(data.failed_symbols)}
        )
    return messages


def discord_embeds_from(data: ReportData) -> list[dict]:
    """Render collected data into Discord embed objects."""
    embeds: list[dict] = []
    if data.snapshot:
        embeds.append(market_embed(data.sentiment, data.snapshot))
    embeds.extend(holding_embed(summary) for summary in data.summaries)
    if data.swing_picks:
        embeds.append(swing_embed(data.swing_picks))
    if data.failed_symbols:
        embeds.append(failed_embed(data.failed_symbols))

    if not embeds:
        raise RuntimeError("分析データを取得できませんでした（全銘柄・市場データの取得に失敗）")
    return embeds


def generate_flex_messages(holdings: list[Holding], include_swing_pick: bool = True) -> list[dict]:
    """Convenience: collect data and render LINE Flex messages in one call."""
    return flex_messages_from(collect_report_data(holdings, include_swing_pick))


def generate_discord_embeds(holdings: list[Holding], include_swing_pick: bool = True) -> list[dict]:
    """Convenience: collect data and render Discord embeds in one call."""
    return discord_embeds_from(collect_report_data(holdings, include_swing_pick))


def main() -> None:
    parser = argparse.ArgumentParser(description="保有銘柄の分析レポートを表示します")
    parser.add_argument("--portfolio", default="portfolio.sample.csv", help="保有銘柄CSVのパス")
    parser.add_argument(
        "--summary", action="store_true", help="LINE通知用の要約レポートを表示する(既定は詳細レポート)"
    )
    args = parser.parse_args()

    holdings = load_portfolio(args.portfolio)
    report = generate_summary(holdings) if args.summary else generate_report(holdings)
    for line in report:
        print(line)


if __name__ == "__main__":
    main()
