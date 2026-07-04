from __future__ import annotations


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
