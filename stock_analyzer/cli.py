from __future__ import annotations

import argparse
from datetime import date

from stock_analyzer.data_fetcher import fetch_fundamentals, fetch_next_earnings_date, fetch_price_history
from stock_analyzer.fundamentals import (
    evaluate_growth,
    evaluate_payout_ratio,
    evaluate_pbr,
    evaluate_per,
    evaluate_roa,
    evaluate_roe,
)
from stock_analyzer.indicators import (
    bollinger_sigma,
    evaluate_bollinger,
    evaluate_macd,
    evaluate_price_position,
    evaluate_volume,
    macd,
    period_high_low,
    relative_strength_index,
    simple_moving_average,
    support_resistance,
)
from stock_analyzer.portfolio import Holding, load_portfolio
from stock_analyzer.scoring import evaluate_recommendation, total_score

SMA_WINDOW = 20
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


def evaluate_signal(rsi: float | None) -> str:
    if rsi is None:
        return "データ不足"
    if rsi <= RSI_OVERSOLD:
        return "買い検討"
    if rsi >= RSI_OVERBOUGHT:
        return "売り検討"
    return "様子見"


def _fmt(value: float | None, spec: str = "{:.2f}") -> str:
    return spec.format(value) if value is not None else "データ不足"


def _build_holding_report(holding: Holding) -> list[str]:
    history = fetch_price_history(holding.symbol)
    closes = history["Close"].tolist()
    highs = history["High"].tolist()
    lows = history["Low"].tolist()
    volumes = history["Volume"].tolist()

    current_price = closes[-1] if closes else None
    sma = simple_moving_average(closes, SMA_WINDOW)
    rsi = relative_strength_index(closes, RSI_PERIOD)
    technical_signal = evaluate_signal(rsi)

    macd_signal = evaluate_macd(macd(closes))
    bollinger_signal = evaluate_bollinger(bollinger_sigma(closes))
    volume_signal = evaluate_volume(volumes)

    levels = support_resistance(highs, lows)
    price_position = (
        evaluate_price_position(current_price, levels) if current_price is not None else "データ不足"
    )
    period_high, period_low = period_high_low(highs, lows)

    fundamentals = fetch_fundamentals(holding.symbol)
    per = fundamentals["per"]
    pbr = fundamentals["pbr"]
    per_signal = evaluate_per(per)
    pbr_signal = evaluate_pbr(pbr)

    roe = fundamentals["roe"]
    roa = fundamentals["roa"]
    eps = fundamentals["eps"]
    bps = fundamentals["bps"]
    revenue_growth = fundamentals["revenue_growth"]
    earnings_growth = fundamentals["earnings_growth"]
    payout_ratio = fundamentals["payout_ratio"]

    next_earnings = fetch_next_earnings_date(holding.symbol)
    days_to_earnings = (next_earnings - date.today()).days if next_earnings else None

    score = total_score(rsi, per, pbr)
    recommendation = evaluate_recommendation(score)

    return [
        f"■ {holding.symbol} ({holding.quantity:.0f}株 @{holding.avg_cost:.2f})",
        f"現在値: {_fmt(current_price)}",
        f"SMA20: {_fmt(sma)} / RSI14: {_fmt(rsi, '{:.1f}')} ({technical_signal})",
        f"MACD: {macd_signal}",
        f"ボリンジャーバンド: {bollinger_signal}",
        f"出来高: {volume_signal}",
        f"価格位置: {price_position}",
        f"52週高値/安値: {_fmt(period_high)} / {_fmt(period_low)}",
        f"PER: {_fmt(per, '{:.1f}')}({per_signal}) / PBR: {_fmt(pbr, '{:.1f}')}({pbr_signal})",
        f"ROE: {_fmt(roe * 100 if roe is not None else None, '{:.1f}%')}({evaluate_roe(roe)}) "
        f"/ ROA: {_fmt(roa * 100 if roa is not None else None, '{:.1f}%')}({evaluate_roa(roa)})",
        f"EPS: {_fmt(eps)} / BPS: {_fmt(bps)}",
        f"売上成長率: {_fmt(revenue_growth * 100 if revenue_growth is not None else None, '{:+.1f}%')}"
        f"({evaluate_growth(revenue_growth, '増収', '減収')}) "
        f"/ 利益成長率: {_fmt(earnings_growth * 100 if earnings_growth is not None else None, '{:+.1f}%')}"
        f"({evaluate_growth(earnings_growth, '増益', '減益')})",
        f"配当性向: {_fmt(payout_ratio * 100 if payout_ratio is not None else None, '{:.1f}%')}"
        f"({evaluate_payout_ratio(payout_ratio)})",
        f"次回決算日: {next_earnings.isoformat() if next_earnings else 'データ不足'}"
        + (f" (あと{days_to_earnings}日)" if days_to_earnings is not None else ""),
        f"総合スコア: {score}/100 ({recommendation})",
    ]


def generate_report(holdings: list[Holding]) -> list[str]:
    """Build the analysis report as a list of lines, one block per holding."""
    lines: list[str] = []
    for holding in holdings:
        lines.extend(_build_holding_report(holding))
        lines.append("")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="保有銘柄のテクニカル分析レポートを表示します")
    parser.add_argument("--portfolio", default="portfolio.sample.csv", help="保有銘柄CSVのパス")
    args = parser.parse_args()

    holdings = load_portfolio(args.portfolio)
    for line in generate_report(holdings):
        print(line)


if __name__ == "__main__":
    main()
