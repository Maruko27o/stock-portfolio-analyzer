"""集中度(保有比率超過)のハード制約 [カテゴリ1]。

個別銘柄スコアリングとポートフォリオ最適化(リバランス)を「独立に」計算していたため、
「保有比率が目標を大きく超えている」のに個別カードは『買い増し』、同一レポートの
リバランス表は『大幅減』という真逆の指示が同時に出ていた。

ここでは、リバランスが算出した推奨(目標)比率と現在比率を個別判断へ必須入力として渡し、
現在比率が目標比率を一定閾値(相対+30% かつ 絶対+5pt)超える銘柄は、ファンダ/テクニカルの
スコアが高くても最終アクションを買い増し系にできないようハードルールでキャップする。

これにより「買い増し」カードと「縮小」リバランスの方向矛盾を発生源で解消する。
検出だけの層(consistency)は、万一すり抜けた矛盾を最終ゲートで捕捉する。
"""

from __future__ import annotations

from dataclasses import dataclass

from stock_analyzer import config
from stock_analyzer.conclusion import BUY_ACTIONS
from stock_analyzer.decision import SCORE_BANDS, HoldingDecision, _comment
from stock_analyzer.rebalance import RebalancePlan

# 買い増しを封じたときに落とす先(据え置き=保有)。
NON_BUY_FLOOR = "保有"


@dataclass
class ConcentrationCap:
    symbol: str
    current_pct: float
    target_pct: float
    before_action: str
    after_action: str


def is_overweight(current_pct: float, target_pct: float) -> bool:
    """現在比率が目標比率を「相対+30% かつ 絶対+5pt」超えていれば True。"""
    rel = current_pct > target_pct * (1 + config.OVERWEIGHT_REL_THRESHOLD)
    absolute = (current_pct - target_pct) >= config.OVERWEIGHT_ABS_THRESHOLD_PT
    return rel and absolute


def _band_range(action: str) -> tuple[int, int, str]:
    """アクションのスコア帯 (low, high, stars) を返す。"""
    for i, (threshold, stars, act) in enumerate(SCORE_BANDS):
        if act == action:
            high = 100 if i == 0 else SCORE_BANDS[i - 1][0] - 1
            return threshold, high, stars
    return 0, 100, SCORE_BANDS[-1][1]


def apply_caps(
    decisions: list[HoldingDecision], rebalance: RebalancePlan | None
) -> list[ConcentrationCap]:
    """保有比率が目標を超え、リバランスが縮小を求める銘柄の買い増しを封じる(その場で書き換え)。

    リバランス表の方向(縮小=売却)を各保有判断へ必須入力として渡し、「買い増しカード」と
    「縮小指示」の方向矛盾を発生源で解消する。目標を大きく超過(相対+30%かつ絶対+5pt)している
    場合は、その旨を根拠に明記する。スコア・★・アクション・コメントを帯整合で更新する。
    戻り値は適用したキャップの一覧(レポートの根拠・監査用)。
    """
    if rebalance is None:
        return []
    by_symbol = {d.symbol: d for d in decisions if not d.is_candidate}
    caps: list[ConcentrationCap] = []
    for it in rebalance.items:
        d = by_symbol.get(it.symbol)
        if d is None or d.action not in BUY_ACTIONS:
            continue
        # リバランスが縮小(売却方向)を求める保有は、個別カードで買い増しにできない。
        if it.direction != "売却":
            continue
        before = d.action
        low, high, stars = _band_range(NON_BUY_FLOOR)
        d.action = NON_BUY_FLOOR
        d.overall_stars = stars
        # スコアも「保有」帯へ収め、スコア・★・アクションの整合を保つ(自己矛盾を作らない)。
        d.overall_score = max(low, min(high, d.overall_score))
        severity = (
            "を大きく超過(相対+{:.0f}%/絶対+{:.0f}pt)".format(
                config.OVERWEIGHT_REL_THRESHOLD * 100, config.OVERWEIGHT_ABS_THRESHOLD_PT
            )
            if is_overweight(it.current_pct, it.target_pct)
            else "を超過"
        )
        note = f"保有比率{it.current_pct:.0f}%が目標{it.target_pct:.0f}%{severity}のため買い増しを解除"
        if note not in d.reasons:
            d.reasons = list(d.reasons) + [note]
        d.comment = _comment(NON_BUY_FLOOR, d.discount_pct, d.earnings_alert, None)
        caps.append(
            ConcentrationCap(d.symbol, it.current_pct, it.target_pct, before, NON_BUY_FLOOR)
        )
    return caps
