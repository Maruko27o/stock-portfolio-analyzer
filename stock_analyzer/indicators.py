from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MACDResult:
    macd: float
    signal: float
    histogram: float
    prev_macd: float
    prev_signal: float


@dataclass
class SupportResistance:
    support: float
    resistance: float


def simple_moving_average(prices: list[float], window: int) -> float | None:
    """Return the SMA of the most recent `window` prices, or None if not enough data."""
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window


def relative_strength_index(prices: list[float], period: int = 14) -> float | None:
    """Return the RSI (0-100) computed over the last `period` price changes."""
    if len(prices) < period + 1:
        return None

    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent_changes = changes[-period:]

    gains = [c for c in recent_changes if c > 0]
    losses = [-c for c in recent_changes if c < 0]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _ema_series(values: list[float], span: int) -> list[float]:
    """Return the EMA of `values` at every point, seeded with the first value."""
    multiplier = 2 / (span + 1)
    ema_values = [values[0]]
    for value in values[1:]:
        ema_values.append((value - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values


def macd(
    prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> MACDResult | None:
    """Return the latest MACD line, signal line, and histogram, or None if not enough data."""
    if len(prices) < slow + signal + 1:
        return None

    ema_fast = _ema_series(prices, fast)
    ema_slow = _ema_series(prices, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema_series(macd_line, signal)

    return MACDResult(
        macd=macd_line[-1],
        signal=signal_line[-1],
        histogram=macd_line[-1] - signal_line[-1],
        prev_macd=macd_line[-2],
        prev_signal=signal_line[-2],
    )


def evaluate_macd(result: MACDResult | None) -> str:
    if result is None:
        return "データ不足"

    crossed_up = result.prev_macd <= result.prev_signal and result.macd > result.signal
    crossed_down = result.prev_macd >= result.prev_signal and result.macd < result.signal

    if crossed_up:
        return "ゴールデンクロス"
    if crossed_down:
        return "デッドクロス"
    return "上昇中" if result.macd > result.signal else "下降中"


def bollinger_sigma(prices: list[float], window: int = 20) -> float | None:
    """Return how many standard deviations the latest price is from its `window`-day SMA."""
    if len(prices) < window:
        return None

    recent = prices[-window:]
    mean = sum(recent) / window
    variance = sum((p - mean) ** 2 for p in recent) / window
    std = variance**0.5

    if std == 0:
        return 0.0
    return (prices[-1] - mean) / std


def evaluate_bollinger(sigma: float | None) -> str:
    if sigma is None:
        return "データ不足"
    if sigma >= 3:
        return "+3σ超(バンドウォーク)"
    if sigma >= 2:
        return "+2σ〜+3σ"
    if sigma >= 1:
        return "+1σ〜+2σ"
    if sigma >= -1:
        return "中央線付近"
    if sigma >= -2:
        return "-1σ〜-2σ"
    if sigma >= -3:
        return "-2σ〜-3σ"
    return "-3σ超(バンドウォーク)"


def evaluate_volume(volumes: list[float], window: int = 20) -> str:
    """Compare the latest volume against the average of the preceding `window` days."""
    if len(volumes) < window + 1:
        return "データ不足"

    today = volumes[-1]
    average = sum(volumes[-window - 1 : -1]) / window
    if average == 0:
        return "データ不足"

    ratio = today / average
    if ratio >= 2.0:
        return f"急増(平均比{ratio:.1f}倍)"
    if ratio >= 1.2:
        return "増加"
    if ratio <= 0.5:
        return "急減"
    if ratio <= 0.8:
        return "減少"
    return "平常"


def support_resistance(highs: list[float], lows: list[float], window: int = 60) -> SupportResistance | None:
    """Return the support (window low) and resistance (window high) over the last `window` days."""
    if len(highs) < window or len(lows) < window:
        return None
    return SupportResistance(support=min(lows[-window:]), resistance=max(highs[-window:]))


def evaluate_price_position(price: float, levels: SupportResistance | None) -> str:
    if levels is None:
        return "データ不足"
    if price >= levels.resistance:
        return "レジスタンスブレイク"
    if price <= levels.support:
        return "サポート割れ"

    to_resistance = (levels.resistance - price) / price * 100
    to_support = (price - levels.support) / price * 100
    return f"レジスタンスまで+{to_resistance:.1f}% / サポートまで-{to_support:.1f}%"


def period_high_low(highs: list[float], lows: list[float]) -> tuple[float | None, float | None]:
    """Return the (high, low) over the given price series, or (None, None) if empty."""
    if not highs or not lows:
        return None, None
    return max(highs), min(lows)
