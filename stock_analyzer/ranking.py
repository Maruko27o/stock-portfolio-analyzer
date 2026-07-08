"""ランキング表示の唯一のソート関数 [カテゴリ11/18]。

「買い優先順位」「新規候補TOP3」など、順位・順序を表示するすべての箇所は必ずこの
関数を経由する。個別実装のソートを各所に散らばらせない(スコア降順の一貫性を保証)。

順位付けは総合スコアの降順を必ず起点にし、同点のときだけ priority_value
(期待リターン×確度の加点)で微調整する。表示順位とスコアは常に降順一致。
"""

from __future__ import annotations

from stock_analyzer.allocation import priority_value
from stock_analyzer.decision import HoldingDecision


def sort_key(d: HoldingDecision) -> tuple[float, float]:
    """降順ソート用キー: (総合スコア, priority_value)。スコアが主・同点時のみ加点で調整。"""
    return (d.overall_score, priority_value(d))


def by_score(decisions: list[HoldingDecision]) -> list[HoldingDecision]:
    """総合スコア降順(同点時のみ priority_value)で並べた新しいリストを返す。"""
    return sorted(decisions, key=sort_key, reverse=True)


def is_score_descending(decisions: list[HoldingDecision]) -> bool:
    """並びが総合スコア降順になっているか(表示直前の検証用)。"""
    scores = [d.overall_score for d in decisions]
    return scores == sorted(scores, reverse=True)
