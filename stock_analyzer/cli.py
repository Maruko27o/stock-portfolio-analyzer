from __future__ import annotations

import argparse
import time

from stock_analyzer.analysis import HoldingAnalysis, analyze_holding
from stock_analyzer.data_fetcher import fetch_fundamentals
from stock_analyzer.fundamentals import (
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
)
from stock_analyzer.flex import holding_bubble, market_bubble, swing_bubble, to_flex_messages
from stock_analyzer.market import evaluate_market_sentiment, fetch_market_snapshot
from stock_analyzer.portfolio import Holding, load_portfolio
from stock_analyzer.screener import build_swing_section, top_swing_picks
from stock_analyzer.scoring import evaluate_recommendation, total_score
from stock_analyzer.summary import build_summary, format_market_header, format_summary


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
        f"配当性向: {_pct(a.payout_ratio)}({evaluate_payout_ratio(a.payout_ratio)})",
        f"次回決算日: {a.next_earnings.isoformat() if a.next_earnings else 'データ不足'}"
        + (f" (あと{a.days_to_earnings}日)" if a.days_to_earnings is not None else ""),
        f"セクター: {a.sector or 'データ不足'} / 業種: {a.industry or 'データ不足'}",
        f"総合スコア: {score}/100 ({evaluate_recommendation(score)})",
    ]


def _market_section() -> tuple[str, list[str]]:
    """Return (sentiment, detailed market lines)."""
    snapshot = fetch_market_snapshot()
    sentiment = evaluate_market_sentiment(snapshot)
    lines = ["【市場環境】", f"市場全体: {sentiment}"]
    for name, (price, change) in snapshot.items():
        lines.append(f"{name}: {_fmt(price)} ({_fmt(change, '{:+.2f}%')})")
    return sentiment, lines


def generate_report(holdings: list[Holding]) -> list[str]:
    """Build the full detailed report (all indicators) — used for local CLI inspection."""
    sentiment, market_lines = _market_section()
    lines: list[str] = [*market_lines, ""]
    for holding in holdings:
        lines.extend(_build_detailed_block(analyze_holding(holding)))
        lines.append("")
    return lines


def generate_summary(holdings: list[Holding], include_swing_pick: bool = True) -> list[str]:
    """Build the concise, AI-selected summary report — used for LINE notifications.

    Holdings are ordered by their overall score, highest first.
    """
    sentiment, _ = _market_section()
    summaries = [build_summary(analyze_holding(holding), sentiment) for holding in holdings]
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


def generate_flex_messages(holdings: list[Holding], include_swing_pick: bool = True) -> list[dict]:
    """Build LINE Flex message objects: a market card, one card per holding, and a swing card.

    Individual failures (a rate-limited or delisted ticker, a market/swing hiccup) are
    tolerated so the notification still goes out with whatever succeeded.
    """
    bubbles: list[dict] = []

    try:
        snapshot = fetch_market_snapshot()
        sentiment = evaluate_market_sentiment(snapshot)
        bubbles.append(market_bubble(sentiment, snapshot))
    except Exception:
        sentiment = "中立"  # neutral fallback so holding scores can still be computed

    summaries = []
    failed_symbols = []
    for holding in holdings:
        try:
            summaries.append(build_summary(_analyze_with_retry(holding), sentiment))
        except Exception:
            failed_symbols.append(holding.symbol)
    summaries.sort(key=lambda s: s.raw_score, reverse=True)
    bubbles.extend(holding_bubble(summary) for summary in summaries)

    if include_swing_pick:
        try:
            picks = top_swing_picks()
        except Exception:
            picks = []
        if picks:
            pick_dicts = []
            for candidate in picks:
                try:
                    name = fetch_fundamentals(candidate.symbol)["name"]
                except Exception:
                    name = None
                heading = f"{candidate.symbol} {name}" if name else candidate.symbol
                pick_dicts.append(
                    {
                        "heading": heading,
                        "score": candidate.score,
                        "current_price": candidate.current_price,
                        "reasons": candidate.reasons,
                    }
                )
            bubbles.append(swing_bubble(pick_dicts))

    if not bubbles:
        # Nothing could be fetched at all (e.g. full rate limit) — fail loudly.
        raise RuntimeError("分析データを取得できませんでした（全銘柄・市場データの取得に失敗）")

    messages: list[dict] = to_flex_messages(bubbles, alt_text="株ポートフォリオ分析")
    if failed_symbols:
        messages.append(
            {"type": "text", "text": "⚠️ 取得できなかった銘柄: " + ", ".join(failed_symbols)}
        )
    return messages


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
