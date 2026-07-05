from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stock_analyzer.data_fetcher import (
    fetch_fundamentals,
    fetch_next_earnings_date,
    fetch_price_history,
)
from stock_analyzer.indicators import (
    MACDResult,
    SupportResistance,
    bollinger_sigma,
    evaluate_volume,
    evaluate_volume_price,
    macd,
    period_high_low,
    rate_of_change,
    relative_strength_index,
    simple_moving_average,
    support_resistance,
    volume_trend,
)
from stock_analyzer.portfolio import Holding

SMA_SHORT = 5
SMA_MID = 25
SMA_LONG = 75
RSI_PERIOD = 14


@dataclass
class HoldingAnalysis:
    """All computed indicators and fundamentals for a single holding."""

    holding: Holding
    name: str | None
    current_price: float | None
    sma_short: float | None
    sma_mid: float | None
    sma_long: float | None
    rsi: float | None
    momentum: float | None
    macd_result: MACDResult | None
    bollinger: float | None
    volume_signal: str
    volume_trend_ratio: float | None
    volume_price_signal: str
    levels: SupportResistance | None
    period_high: float | None
    period_low: float | None
    per: float | None
    pbr: float | None
    dividend_yield: float | None
    roe: float | None
    roa: float | None
    eps: float | None
    bps: float | None
    revenue_growth: float | None
    earnings_growth: float | None
    payout_ratio: float | None
    debt_to_equity: float | None
    current_ratio: float | None
    sector: str | None
    industry: str | None
    next_earnings: date | None
    days_to_earnings: int | None
    dividend_rate: float | None = None  # annual dividend per share (currency)
    ex_dividend_date: date | None = None
    days_to_ex_dividend: int | None = None

    @property
    def profit_pct(self) -> float | None:
        if self.current_price is None or not self.holding.avg_cost:
            return None
        return (self.current_price - self.holding.avg_cost) / self.holding.avg_cost * 100

    @property
    def yield_on_cost(self) -> float | None:
        """Dividend yield against the user's own average cost, not the current price."""
        if self.dividend_rate is None or not self.holding.avg_cost:
            return None
        return self.dividend_rate / self.holding.avg_cost * 100


def analyze_holding(holding: Holding) -> HoldingAnalysis:
    """Fetch data and compute every indicator/fundamental for one holding."""
    history = fetch_price_history(holding.symbol)
    closes = history["Close"].tolist()
    highs = history["High"].tolist()
    lows = history["Low"].tolist()
    volumes = history["Volume"].tolist()

    fundamentals = fetch_fundamentals(holding.symbol)
    next_earnings = fetch_next_earnings_date(holding.symbol)
    days_to_earnings = (next_earnings - date.today()).days if next_earnings else None
    ex_dividend_date = fundamentals["ex_dividend_date"]
    days_to_ex_dividend = (ex_dividend_date - date.today()).days if ex_dividend_date else None
    period_high, period_low = period_high_low(highs, lows)

    return HoldingAnalysis(
        holding=holding,
        name=holding.name or fundamentals["name"],
        current_price=closes[-1] if closes else None,
        sma_short=simple_moving_average(closes, SMA_SHORT),
        sma_mid=simple_moving_average(closes, SMA_MID),
        sma_long=simple_moving_average(closes, SMA_LONG),
        rsi=relative_strength_index(closes, RSI_PERIOD),
        momentum=rate_of_change(closes, 10),
        macd_result=macd(closes),
        bollinger=bollinger_sigma(closes),
        volume_signal=evaluate_volume(volumes),
        volume_trend_ratio=volume_trend(volumes),
        volume_price_signal=evaluate_volume_price(closes, volumes),
        levels=support_resistance(highs, lows),
        period_high=period_high,
        period_low=period_low,
        per=fundamentals["per"],
        pbr=fundamentals["pbr"],
        dividend_yield=fundamentals["dividend_yield"],
        roe=fundamentals["roe"],
        roa=fundamentals["roa"],
        eps=fundamentals["eps"],
        bps=fundamentals["bps"],
        revenue_growth=fundamentals["revenue_growth"],
        earnings_growth=fundamentals["earnings_growth"],
        payout_ratio=fundamentals["payout_ratio"],
        debt_to_equity=fundamentals["debt_to_equity"],
        current_ratio=fundamentals["current_ratio"],
        sector=fundamentals["sector"],
        industry=fundamentals["industry"],
        next_earnings=next_earnings,
        days_to_earnings=days_to_earnings,
        dividend_rate=fundamentals["dividend_rate"],
        ex_dividend_date=ex_dividend_date,
        days_to_ex_dividend=days_to_ex_dividend,
    )
