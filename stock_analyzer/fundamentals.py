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
