"""適正価格と割安率の推定。

「適正価格」はセクター別の標準PER×EPSと、アナリスト目標株価(平均)の合成。
どちらもヒューリスティックな目安であり、確定値ではない点に注意。
両者が欠損すれば None を返す(捏造しない)。
"""

from __future__ import annotations

from stock_analyzer import config
from stock_analyzer.analysis import HoldingAnalysis


def fair_value(analysis: HoldingAnalysis) -> float | None:
    """適正価格の目安。セクター標準PER×EPS と アナリスト目標株価平均の平均。

    どちらか一方しか取れなければそれを採用。両方欠損なら None。
    """
    candidates: list[float] = []
    if analysis.eps is not None and analysis.eps > 0:
        per_based = config.per_threshold(analysis.sector) * analysis.eps
        # PERモデルはアナリストの最強気目標を超えて割安を主張しない(上限クリップ)。
        # 空運など構造的に低PERの業種で、一律のセクターPERが適正価格を過大にするのを防ぐ。
        if analysis.target_high_price is not None and analysis.target_high_price > 0:
            per_based = min(per_based, analysis.target_high_price)
        candidates.append(per_based)
    if analysis.target_mean_price is not None and analysis.target_mean_price > 0:
        candidates.append(analysis.target_mean_price)
    if not candidates:
        return None
    return sum(candidates) / len(candidates)


def discount_pct(analysis: HoldingAnalysis) -> float | None:
    """割安率 = (現在価格 − 適正価格) / 適正価格 × 100。

    負なら割安(現在が適正より安い)、正なら割高。例: 現在3445/適正3820 → −9.8%。
    """
    fv = fair_value(analysis)
    if fv is None or fv <= 0 or analysis.current_price is None:
        return None
    return (analysis.current_price - fv) / fv * 100


def analyst_upside_pct(analysis: HoldingAnalysis) -> float | None:
    """アナリスト目標株価(平均)までの上値余地 %。目標が無ければ None。"""
    tgt = analysis.target_mean_price
    if tgt is None or tgt <= 0 or analysis.current_price is None or analysis.current_price <= 0:
        return None
    return (tgt - analysis.current_price) / analysis.current_price * 100
