from __future__ import annotations

import argparse

from stock_analyzer.data_fetcher import fetch_closing_prices
from stock_analyzer.indicators import relative_strength_index, simple_moving_average
from stock_analyzer.portfolio import load_portfolio

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


def main() -> None:
    parser = argparse.ArgumentParser(description="保有銘柄のテクニカル分析レポートを表示します")
    parser.add_argument("--portfolio", default="portfolio.sample.csv", help="保有銘柄CSVのパス")
    args = parser.parse_args()

    holdings = load_portfolio(args.portfolio)

    header = f"{'銘柄':<8}{'保有数':>8}{'現在値':>10}{'SMA20':>10}{'RSI14':>8}  判定"
    print(header)
    print("-" * len(header))

    for holding in holdings:
        prices = fetch_closing_prices(holding.symbol)
        current_price = prices[-1] if prices else None
        sma = simple_moving_average(prices, SMA_WINDOW)
        rsi = relative_strength_index(prices, RSI_PERIOD)
        signal = evaluate_signal(rsi)

        print(
            f"{holding.symbol:<8}"
            f"{holding.quantity:>8.0f}"
            f"{current_price:>10.2f}"
            f"{sma if sma is not None else 0:>10.2f}"
            f"{rsi if rsi is not None else 0:>8.1f}  {signal}"
        )


if __name__ == "__main__":
    main()
