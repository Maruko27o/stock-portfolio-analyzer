"""保有ポートフォリオのリバランス差分。

allocation.py が「次に入れる資金の配分」を扱うのに対し、こちらは
「今の保有評価額の内訳を、推奨比率へどう寄せるか」を扱う。
現在比率(評価額ベース)→推奨比率を銘柄ごとに出し、増やす/減らす方向と
概算株数まで示す。仕様の「SBI 40%→25%は15%売却」に対応する層。

推奨比率は各保有の魅力度(allocation.priority_value)で決めるが、
- 売却シグナル(一部売却/売却推奨)の銘柄は推奨比率を機械的に引き下げ、
- 1銘柄・1セクターの上限(config)を超えないようにクリップし、
- 現金を含めた全体で正規化する(現金比率は allocation の推奨を尊重)。
透明性重視で、ブラックボックス最適化はしない。
"""

from __future__ import annotations

from dataclasses import dataclass

from stock_analyzer import config
from stock_analyzer.allocation import priority_value
from stock_analyzer.decision import SELL_ACTIONS, HoldingDecision

# 売却シグナルの推奨比率の抑制係数(魅力度に掛ける)。
SELL_DAMPEN = {"一部売却": 0.4, "売却推奨": 0.0}

# 現在比率と推奨比率の差がこの%未満なら「維持」とみなす(小さな乖離で売買させない)。
DRIFT_TOLERANCE_PCT = 3.0


@dataclass
class RebalanceItem:
    symbol: str
    name: str | None
    current_pct: float  # 現在の評価額比率(保有内、%)
    target_pct: float  # 推奨比率(保有内、%)
    diff_pct: float  # target − current(正=買い増し / 負=売却)
    direction: str  # "買い増し" | "売却" | "維持"
    approx_shares: int | None  # 概算売買株数(現在値が取れる時のみ)
    current_price: float | None


@dataclass
class RebalancePlan:
    items: list[RebalanceItem]  # 現在比率の降順
    total_value_yen: float | None  # 保有総評価額(算出できた分)
    note: str


def _market_value(decision: HoldingDecision, quantity: float) -> float | None:
    if decision.current_price is None or quantity <= 0:
        return None
    return decision.current_price * quantity


def build_rebalance(
    decisions: list[HoldingDecision],
    quantities: dict[str, float],
) -> RebalancePlan:
    """保有 decisions と数量から現在比率→推奨比率の差分を作る。

    quantities は {symbol: 保有株数}。新規候補(is_candidate)は対象外。
    """
    held = [d for d in decisions if not d.is_candidate and quantities.get(d.symbol, 0) > 0]

    values: dict[str, float] = {}
    for d in held:
        mv = _market_value(d, quantities.get(d.symbol, 0.0))
        if mv is not None:
            values[d.symbol] = mv
    total = sum(values.values())

    if total <= 0:
        return RebalancePlan(items=[], total_value_yen=None, note="評価額を算出できませんでした")

    # 推奨(生)ウェイト = 魅力度に売却シグナルの抑制を掛けたもの。
    raw: dict[str, float] = {}
    for d in held:
        attractiveness = max(0.0, priority_value(d))
        dampen = SELL_DAMPEN.get(d.action, 1.0)
        raw[d.symbol] = attractiveness * dampen

    # 銘柄上限でクリップ → 正規化(保有内の比率なので合計100%)。
    raw_total = sum(raw.values())
    if raw_total <= 0:
        # 全銘柄が売却シグナル等でゼロ → 現状維持を推奨(機械的な全売りはしない)。
        target = {sym: values[sym] / total for sym in values}
    else:
        target = {sym: raw[sym] / raw_total for sym in raw}
        target = {sym: min(w, config.ALLOC_NAME_CAP) for sym, w in target.items()}
        clipped_total = sum(target.values())
        if clipped_total > 0:
            target = {sym: w / clipped_total for sym, w in target.items()}

    items: list[RebalanceItem] = []
    for d in held:
        if d.symbol not in values:
            continue
        current = values[d.symbol] / total * 100
        tgt = target.get(d.symbol, 0.0) * 100
        diff = tgt - current
        if abs(diff) < DRIFT_TOLERANCE_PCT:
            direction = "維持"
        elif diff > 0:
            direction = "買い増し"
        else:
            direction = "売却"

        approx_shares = None
        if d.current_price and d.current_price > 0 and direction != "維持":
            approx_shares = abs(round(diff / 100 * total / d.current_price))
            if approx_shares == 0:
                direction = "維持"
                approx_shares = None

        items.append(
            RebalanceItem(
                symbol=d.symbol,
                name=d.name,
                current_pct=current,
                target_pct=tgt,
                diff_pct=diff,
                direction=direction,
                approx_shares=approx_shares,
                current_price=d.current_price,
            )
        )

    items.sort(key=lambda it: it.current_pct, reverse=True)

    over = [it for it in items if it.direction == "売却"]
    under = [it for it in items if it.direction == "買い増し"]
    parts = []
    if over:
        parts.append("比率が高すぎる銘柄あり(縮小推奨)")
    if under:
        parts.append("比率が低い有望銘柄あり(拡大余地)")
    note = "／".join(parts) if parts else "概ね推奨比率どおり(大きなリバランス不要)"

    return RebalancePlan(items=items, total_value_yen=total, note=note)


def format_rebalance_lines(plan: RebalancePlan, top_n: int = 8) -> list[str]:
    """CLI/テキスト用にリバランス差分を整形する。"""
    if not plan.items:
        return []
    lines = ["■リバランス(現在比率→推奨比率)"]
    for it in plan.items[:top_n]:
        arrow = {"買い増し": "▲", "売却": "▼", "維持": "＝"}.get(it.direction, "")
        shares = f"（約{it.approx_shares}株{it.direction}）" if it.approx_shares else ""
        lines.append(
            f"{arrow} {it.name or it.symbol}：{it.current_pct:.0f}% → {it.target_pct:.0f}%"
            f"（{it.diff_pct:+.0f}%）{shares}"
        )
    lines.append(f"分散: {plan.note}")
    return lines
