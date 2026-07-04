from __future__ import annotations

RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
PER_THRESHOLD = 15.0
PBR_THRESHOLD = 1.0

BUY_THRESHOLD = 70
SELL_THRESHOLD = 30


def technical_score(rsi: float | None) -> int:
    """Score 0-50 from RSI: higher means more oversold (bullish)."""
    if rsi is None:
        return 25
    if rsi <= RSI_OVERSOLD:
        return 50
    if rsi >= RSI_OVERBOUGHT:
        return 0
    return 25


def fundamental_score(per: float | None, pbr: float | None) -> int:
    """Score 0-50 from PER/PBR: higher means cheaper (bullish)."""

    def field_score(value: float | None, threshold: float) -> int:
        if value is None:
            return 12
        return 25 if value <= threshold else 0

    return field_score(per, PER_THRESHOLD) + field_score(pbr, PBR_THRESHOLD)


def total_score(rsi: float | None, per: float | None, pbr: float | None) -> int:
    """Combined technical + fundamental score, 0-100."""
    return technical_score(rsi) + fundamental_score(per, pbr)


def evaluate_recommendation(score: int) -> str:
    if score >= BUY_THRESHOLD:
        return "買い"
    if score <= SELL_THRESHOLD:
        return "売り"
    return "様子見"
