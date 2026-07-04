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
