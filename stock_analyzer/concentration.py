"""個別カードとポートフォリオ最適化(リバランス)の意思決定を統合する層 [カテゴリ1/10]。

個別銘柄スコアリングとポート最適化を独立に計算していたため、個別カードの推奨アクションと
リバランス表の増減指示が逆方向になる矛盾が繰り返し発生していた。

役割分担を明示して単一パイプラインに統合する:
- ポジションサイズ(増やす/維持/減らす)の意思決定は「ポート最適化(リバランス)」が上位。
- 銘柄選択の質(スコア・★)は「スコアリング」が担当。

そのため保有銘柄の最終アクションは、リバランス方向を正として整合させる:
- リバランスが「縮小(売却方向)」→ 買い/中立カードは「一部売却(サイズ調整)」へ。
  スコア(=質)は保持し、サイズ調整由来であることを sizing_trim で記録する。
- リバランスが「買い増し」→ 売りカードは「保有」へ中立化(質と逆でも強制売りにしない)。
矛盾を発生源で解消し、最終段の整合チェック(consistency)は取りこぼしの安全網とする。
"""

from __future__ import annotations

from dataclasses import dataclass

from stock_analyzer import config
from stock_analyzer.conclusion import BUY_ACTIONS
from stock_analyzer.decision import (
    SELL_ACTIONS,
    HoldingDecision,
    _comment,
    stars_from_score,
)
from stock_analyzer.rebalance import RebalancePlan

NEUTRAL_ACTIONS = {"保有", "様子見"}
TRIM_ACTION = "一部売却"  # リバランス縮小に合わせるサイズ調整の売り


@dataclass
class Reconciliation:
    symbol: str
    before_action: str
    after_action: str
    current_pct: float
    target_pct: float
    reason: str


def is_overweight(current_pct: float, target_pct: float) -> bool:
    """現在比率が目標比率を「相対+30% かつ 絶対+5pt」超えていれば True(大きく超過の判定)。"""
    rel = current_pct > target_pct * (1 + config.OVERWEIGHT_REL_THRESHOLD)
    absolute = (current_pct - target_pct) >= config.OVERWEIGHT_ABS_THRESHOLD_PT
    return rel and absolute


def _apply(d: HoldingDecision, action: str, note: str, sizing_trim: bool) -> None:
    """アクションを設定し、★は決定的関数から、コメントを刷新、理由を追加する。

    スコア(=銘柄選択の質)はサイズ調整では保持する(質はスコアリングの担当)。
    """
    d.action = action
    d.sizing_trim = sizing_trim
    d.overall_stars = stars_from_score(d.overall_score)  # ★はスコア由来[カテゴリ12](帯で上書きしない)
    d.comment = _comment(action, d.discount_pct, d.earnings_alert, None)
    if note not in d.reasons:
        d.reasons = list(d.reasons) + [note]


def reconcile_with_rebalance(
    decisions: list[HoldingDecision], rebalance: RebalancePlan | None
) -> list[Reconciliation]:
    """保有カードの方向をリバランス(サイズ決定の上位)に整合させる(その場で書き換え)。

    戻り値は適用した整合の一覧(レポートの根拠・監査用)。
    """
    if rebalance is None:
        return []
    by_symbol = {d.symbol: d for d in decisions if not d.is_candidate}
    changes: list[Reconciliation] = []
    for it in rebalance.items:
        d = by_symbol.get(it.symbol)
        if d is None:
            continue
        before = d.action
        if it.direction == "売却" and d.action in (BUY_ACTIONS | NEUTRAL_ACTIONS):
            severity = "を大きく超過" if is_overweight(it.current_pct, it.target_pct) else "を超過"
            note = (
                f"保有比率{it.current_pct:.0f}%が目標{it.target_pct:.0f}%{severity}"
                "→ポート最適化に合わせサイズ調整(一部売却)。銘柄の質評価は据え置き"
            )
            _apply(d, TRIM_ACTION, note, sizing_trim=True)
            changes.append(
                Reconciliation(d.symbol, before, TRIM_ACTION, it.current_pct, it.target_pct, note)
            )
        elif it.direction == "買い増し" and d.action in SELL_ACTIONS:
            note = (
                f"ポート最適化は buy方向(目標{it.target_pct:.0f}%>現在{it.current_pct:.0f}%)。"
                "売りシグナルと逆のため保有で中立化"
            )
            _apply(d, "保有", note, sizing_trim=False)
            changes.append(
                Reconciliation(d.symbol, before, "保有", it.current_pct, it.target_pct, note)
            )
    return changes


# 後方互換: 旧名 apply_caps は reconcile_with_rebalance のエイリアス。
def apply_caps(decisions, rebalance):
    return reconcile_with_rebalance(decisions, rebalance)
