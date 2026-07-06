"""ポートフォリオ全体の最適化。

「次に投資する資金をどの銘柄へ何%配分するか」をルールベースで提案する。
保有銘柄と新規候補を統合して買い優先順位を付け、スコア/期待値からターゲット比率を
作り、銘柄上限・セクター上限・相場に応じた現金下限を適用する。透明性重視。

配分は「次の投資額の配分」であり、現在の保有評価額の配分ではない。
想定配当利回り・期待リターン・リスクは、この配分に投資した場合の加重平均で示す。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stock_analyzer import config
from stock_analyzer.decision import HoldingDecision

# 6段階のうち、新規資金の配分対象にしないアクション(保有継続はするが買い増さない)。
NO_ADD_ACTIONS = {"一部売却", "売却推奨", "様子見"}


@dataclass
class AllocationPlan:
    ranking: list[HoldingDecision]  # 買い優先順位(降順)。rank/alloc_pct は各要素に反映済み
    weights: dict[str, float]  # {symbol: 配分%}(現金を除く)
    cash_pct: float  # 現金比率(%)
    sector_breakdown: dict[str, float]  # {sector: 配分%}(投資分のみ)
    expected_dividend_yield: float | None  # 配分の加重平均 配当利回り(%)
    portfolio_expected_return: float | None  # 配分の加重平均 半年〜1年 期待リターン(%)
    portfolio_risk: float | None  # 配分の加重平均 日次変動率(%)
    diversification_note: str


def _long_term_pct(decision: HoldingDecision) -> float | None:
    for h in decision.expected_returns:
        if h.label == "半年〜1年":
            return h.pct
    return None


def _long_term_stars(decision: HoldingDecision) -> int:
    for h in decision.expected_returns:
        if h.label == "半年〜1年" and h.stars:
            return h.stars.count("★")
    return 0


def priority_value(decision: HoldingDecision) -> float:
    """買い優先順位の指標。スコアを基礎に、期待リターン×信頼度を加点する。"""
    lt = _long_term_pct(decision)
    bonus = 0.0
    if lt is not None:
        confidence = _long_term_stars(decision) / 5.0
        bonus = max(-20.0, min(30.0, lt)) * confidence
    return decision.overall_score + bonus


def _rank(decisions: list[HoldingDecision]) -> list[HoldingDecision]:
    ranked = sorted(decisions, key=priority_value, reverse=True)
    for i, d in enumerate(ranked, start=1):
        d.rank = i
    return ranked


def _weighted_avg(pairs: list[tuple[float, float | None]]) -> float | None:
    """[(weight_frac, value)] の加重平均。value=None は除外。全部Noneなら None。"""
    total_w = sum(w for w, v in pairs if v is not None)
    if total_w <= 0:
        return None
    return sum(w * v for w, v in pairs if v is not None) / total_w


def _diversification_note(sector_breakdown: dict[str, float], cash_pct: float, n_names: int) -> str:
    if not sector_breakdown:
        return "投資対象なし(現金で待機)"
    top_sector, top_w = max(sector_breakdown.items(), key=lambda kv: kv[1])
    notes = []
    if top_w >= config.ALLOC_SECTOR_CAP * 100 - 0.5:
        notes.append(f"{top_sector}に上限まで配分(偏り注意)")
    elif top_w >= 40:
        notes.append(f"{top_sector}にやや集中")
    if cash_pct >= 40:
        notes.append("現金を厚めに温存")
    if n_names >= 4 and top_w < 40:
        notes.append("複数銘柄・セクターに分散")
    return "／".join(notes) if notes else "概ね分散"


SCORE_CAVEAT = "※スコアは現在のシグナル整合度。過去検証では帯間の勝率差は小さい点に留意"


def format_allocation_lines(plan: "AllocationPlan", top_n: int = 5) -> list[str]:
    """CLI/テキスト用にポート全体の判断を整形する。"""
    lines = ["🤖 AIファンドマネージャー判断", ""]
    if plan.ranking:
        lines.append("■買い優先順位")
        for d in plan.ranking[:top_n]:
            tag = "（新規）" if d.is_candidate else ""
            lines.append(f"{d.rank}位 {d.symbol} {d.name or ''}{tag} {d.overall_stars} {d.action}")
    if plan.weights:
        lines.append("")
        lines.append("■次の投資資金の配分")
        for d in plan.ranking:
            if d.symbol in plan.weights:
                lines.append(f"{d.name or d.symbol} {plan.weights[d.symbol]:.0f}%")
        lines.append(f"現金 {plan.cash_pct:.0f}%")
    lines.append("")
    stats = [f"現金比率 {plan.cash_pct:.0f}%"]
    if plan.expected_dividend_yield is not None:
        stats.append(f"想定配当利回り {plan.expected_dividend_yield:.1f}%")
    if plan.portfolio_expected_return is not None:
        stats.append(f"期待リターン(半年〜1年) {plan.portfolio_expected_return:+.1f}%")
    if plan.portfolio_risk is not None:
        stats.append(f"日次変動率 {plan.portfolio_risk:.1f}%")
    lines.append(" ／ ".join(stats))
    if plan.sector_breakdown:
        sectors = sorted(plan.sector_breakdown.items(), key=lambda kv: kv[1], reverse=True)
        lines.append("セクター: " + " / ".join(f"{s} {w:.0f}%" for s, w in sectors))
    lines.append(f"分散: {plan.diversification_note}")
    lines.append(SCORE_CAVEAT)
    return lines


def optimize_allocation(
    decisions: list[HoldingDecision],
    regime: str | None = None,
    vix: float | None = None,
) -> AllocationPlan:
    """保有＋新規候補の decisions から配分計画を作る。

    regime/vix は現金下限の決定に使う。各 decision の rank/alloc_pct を書き換える。
    """
    ranking = _rank(decisions)
    floor = config.cash_floor(regime, vix)
    invest_budget = 1.0 - floor  # 投資に回せる上限(残りは最低現金)

    # 新規配分の対象: 一定スコア以上かつ買い増し方向
    eligible = [
        d
        for d in ranking
        if d.overall_score >= config.ALLOC_MIN_SCORE and d.action not in NO_ADD_ACTIONS
    ]

    # 生ウェイト = 優先度からしきい値を引いた超過分(魅力度に比例)
    raw = {d.symbol: max(0.0, priority_value(d) - config.ALLOC_MIN_SCORE) for d in eligible}
    raw_total = sum(raw.values())

    weights: dict[str, float] = {}  # fraction (0-1)
    if raw_total > 0:
        # しきい値超過分で投資予算を按分
        alloc = {sym: raw[sym] / raw_total * invest_budget for sym in raw}
        # 銘柄上限でクリップ
        alloc = {sym: min(w, config.ALLOC_NAME_CAP) for sym, w in alloc.items()}
        # セクター上限でクリップ(超過セクターは比例縮小)
        by_sector: dict[str, list[str]] = {}
        for d in eligible:
            by_sector.setdefault(d.sector or "その他", []).append(d.symbol)
        for syms in by_sector.values():
            sector_sum = sum(alloc[s] for s in syms)
            if sector_sum > config.ALLOC_SECTOR_CAP:
                scale = config.ALLOC_SECTOR_CAP / sector_sum
                for s in syms:
                    alloc[s] *= scale
        weights = {sym: w for sym, w in alloc.items() if w > 0}

    invested = sum(weights.values())
    cash = 1.0 - invested  # クリップで余った分は現金へ(保守側)

    # 表示用に百分率へ。各 decision へも反映。
    weights_pct = {sym: w * 100 for sym, w in weights.items()}
    for d in ranking:
        d.alloc_pct = weights_pct.get(d.symbol)

    sector_breakdown: dict[str, float] = {}
    for d in eligible:
        if d.symbol in weights:
            sector_breakdown[d.sector or "その他"] = sector_breakdown.get(
                d.sector or "その他", 0.0
            ) + weights_pct[d.symbol]

    pairs = [(weights[d.symbol], d) for d in eligible if d.symbol in weights]
    exp_div = _weighted_avg([(w, d.dividend_yield) for w, d in pairs])
    exp_ret = _weighted_avg([(w, _long_term_pct(d)) for w, d in pairs])
    risk = _weighted_avg([(w, d.volatility_pct) for w, d in pairs])

    note = _diversification_note(sector_breakdown, cash * 100, len(weights))

    return AllocationPlan(
        ranking=ranking,
        weights=weights_pct,
        cash_pct=cash * 100,
        sector_breakdown=sector_breakdown,
        expected_dividend_yield=exp_div,
        portfolio_expected_return=exp_ret,
        portfolio_risk=risk,
        diversification_note=note,
    )
