from __future__ import annotations


def evaluate_per(per: float | None, threshold: float = 15.0) -> str:
    """Judge PER (price-to-earnings ratio) as cheap/expensive against a threshold."""
    if per is None:
        return "データ不足"
    return "割安" if per <= threshold else "割高"


def evaluate_pbr(pbr: float | None, threshold: float = 1.0) -> str:
    """Judge PBR (price-to-book ratio) as cheap/expensive against a threshold."""
    if pbr is None:
        return "データ不足"
    return "割安" if pbr <= threshold else "割高"


def evaluate_roe(roe: float | None, threshold: float = 0.08) -> str:
    """Judge ROE (return on equity, as a decimal) against a threshold."""
    if roe is None:
        return "データ不足"
    return "良好" if roe >= threshold else "低い"


def evaluate_roa(roa: float | None, threshold: float = 0.05) -> str:
    """Judge ROA (return on assets, as a decimal) against a threshold."""
    if roa is None:
        return "データ不足"
    return "良好" if roa >= threshold else "低い"


def evaluate_growth(growth: float | None, positive_label: str, negative_label: str) -> str:
    """Judge a YoY growth rate (as a decimal) as positive or negative."""
    if growth is None:
        return "データ不足"
    return positive_label if growth > 0 else negative_label


def evaluate_payout_ratio(payout_ratio: float | None, threshold: float = 0.8) -> str:
    """Judge the dividend payout ratio (as a decimal) for sustainability."""
    if payout_ratio is None:
        return "データ不足"
    return "高い(要注意)" if payout_ratio >= threshold else "適正"


def evaluate_dividend_yield(dividend_yield: float | None, threshold: float = 3.0) -> str:
    """Judge the dividend yield (as a percentage, e.g. 3.5 = 3.5%)."""
    if dividend_yield is None:
        return "データ不足"
    return "高配当" if dividend_yield >= threshold else "標準"


def evaluate_debt_to_equity(debt_to_equity: float | None) -> str:
    """Judge leverage from the debt-to-equity ratio (as a percentage, e.g. 100 = 1.0x)."""
    if debt_to_equity is None:
        return "データ不足"
    if debt_to_equity <= 100:
        return "健全(低負債)"
    if debt_to_equity <= 200:
        return "標準"
    return "負債が多い"


def evaluate_current_ratio(current_ratio: float | None, threshold: float = 1.0) -> str:
    """Judge short-term solvency from the current ratio."""
    if current_ratio is None:
        return "データ不足"
    return "支払い余力あり" if current_ratio >= threshold else "短期支払いに注意"
