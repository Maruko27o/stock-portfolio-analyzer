"""自己採点AI: 分析を10項目で自己採点し、90点未満の項目だけ自動修正する。

各項目100点満点で採点し、90点未満があればその項目に対応する修正だけを当てて、
全項目90点以上になるまで最大5回改善する。採点・レビュー内容は表示せず、改善後の
最終分析だけを残す(呼び出し側が review を非表示にする)。無料・決定論的。

採点は「使える情報の範囲で分析の質が担保されているか」を測る(取得できない信用/貸借/
空売り等を持っていないこと自体は減点しない=誠実ラベルの範囲で満点を認める)。
"""

from __future__ import annotations

from stock_analyzer.conclusion import BUY_ACTIONS
from stock_analyzer.decision import SELL_ACTIONS, HoldingDecision
from stock_analyzer.optimize import compress
from stock_analyzer.review import rule_based_review
from stock_analyzer import self_improve

DIMENSIONS = [
    "分析精度", "説明性", "整合性", "ファンダメンタル", "テクニカル",
    "需給", "ポートフォリオ", "期待値", "リスク管理", "文章品質",
]
TARGET = 90
MAX_ITERATIONS = 5
MAX_ITEM_CHARS = 100


def _all_decisions(decisions, allocation) -> list[HoldingDecision]:
    pool = list(decisions)
    if allocation is not None:
        seen = {id(d) for d in pool}
        for d in allocation.ranking:
            if id(d) not in seen:
                pool.append(d)
    return pool


def _long_term(d: HoldingDecision):
    return next((h for h in d.expected_returns if h.label == "半年〜1年"), None)


def _frac_missing(items: list, predicate) -> float:
    if not items:
        return 0.0
    missing = sum(1 for x in items if not predicate(x))
    return missing / len(items)


def _clamp(score: float) -> int:
    return max(0, min(100, round(score)))


def evaluate(decisions, allocation, review) -> dict[str, int]:
    """10項目を0-100で採点する(高いほど良い)。"""
    pool = _all_decisions(decisions, allocation)
    cat = lambda c: sum(1 for f in review if f.category.startswith(c))  # noqa: E731

    scores: dict[str, int] = {}
    # 分析精度: レビュー指摘の総数(残りの矛盾/過大)で減点
    scores["分析精度"] = _clamp(100 - 9 * len(review))
    # 整合性: ロジック矛盾の数で減点
    scores["整合性"] = _clamp(100 - 14 * cat("1."))
    # 期待値: 期待値過大(7.スコア)で減点
    scores["期待値"] = _clamp(100 - 12 * cat("7."))
    # 説明性: コメント/理由と、数値根拠(割安/配当/期待)が揃っているか
    miss_reason = _frac_missing(pool, lambda d: d.comment or d.reasons)
    miss_basis = _frac_missing(
        pool, lambda d: d.discount_pct is not None or d.dividend_yield or _long_term(d)
    )
    scores["説明性"] = _clamp(100 - 45 * miss_reason - 25 * miss_basis - 10 * cat("6."))
    # ファンダメンタル: 割安率(適正価格)か配当の裏付けがあるか
    miss_fund = _frac_missing(pool, lambda d: d.discount_pct is not None or d.dividend_yield)
    scores["ファンダメンタル"] = _clamp(100 - 35 * miss_fund)
    # テクニカル: 需給★やRR(損切/利確)などテクニカル材料があるか
    miss_tech = _frac_missing(pool, lambda d: d.supply_demand_stars or d.risk_reward is not None)
    scores["テクニカル"] = _clamp(100 - 35 * miss_tech)
    # 需給: 需給★(プロキシ)が算出・表示できているか(誠実ラベルの範囲で満点可)
    miss_sd = _frac_missing(pool, lambda d: d.supply_demand_stars)
    scores["需給"] = _clamp(100 - 30 * miss_sd)
    # ポートフォリオ: セクター偏り/現金比率の健全性
    port = 100
    if allocation is not None:
        if allocation.sector_breakdown:
            top = max(allocation.sector_breakdown.values())
            if top > 36:
                port -= min(30, (top - 36))
        if allocation.cash_pct >= 95 and any(d.action in BUY_ACTIONS for d in pool):
            port -= 10  # 買い候補があるのに現金ほぼ100%は配分不全
    scores["ポートフォリオ"] = _clamp(port)
    # リスク管理: 決算跨ぎの買い・買いなのに損益比(RR)不明で減点
    earnings_buys = sum(1 for d in pool if d.earnings_alert and d.action in BUY_ACTIONS)
    miss_rr = _frac_missing(pool, lambda d: d.risk_reward is not None or d.action not in BUY_ACTIONS)
    scores["リスク管理"] = _clamp(100 - 15 * earnings_buys - 20 * miss_rr - 10 * cat("4."))
    # 文章品質: 100字超の項目・重複理由・圧縮余地で減点
    long_items = sum(1 for d in pool for t in [d.comment, *d.reasons] if t and len(t) > MAX_ITEM_CHARS)
    dup = sum(len(d.reasons) - len(set(d.reasons)) for d in pool)
    compressible = sum(
        1 for d in pool for t in [d.comment] if t and len(compress(t)) < len(t)
    )
    scores["文章品質"] = _clamp(100 - 10 * long_items - 5 * dup - 3 * compressible)
    return scores


# --------------------------------------------------------------------------
# 90点未満の項目だけを直す自動修正
# --------------------------------------------------------------------------

def _supplement_reasons(pool: list[HoldingDecision]) -> None:
    """説明性/ファンダ/テクニカルの補強: 理由が空なら手元の数値から根拠を足す。"""
    for d in pool:
        if d.reasons:
            continue
        bits = []
        if d.discount_pct is not None:
            bits.append(f"適正比{d.discount_pct:+.0f}%")
        lt = _long_term(d)
        if lt is not None and lt.pct is not None:
            bits.append(f"半年〜1年{lt.pct:+.0f}%")
        if d.dividend_yield:
            bits.append(f"配当{d.dividend_yield:.1f}%")
        if d.supply_demand_stars:
            bits.append(f"需給{d.supply_demand_stars}")
        if bits:
            d.reasons = bits


def _supplement_risk(pool: list[HoldingDecision]) -> None:
    """リスク管理の補強: 決算跨ぎの買いは据え置き、根拠を明示。"""
    for d in pool:
        if d.earnings_alert and d.action in BUY_ACTIONS:
            self_improve._set_action(
                d, "保有", f"決算まで{d.days_to_earnings}日のため決算後まで買いを待つ",
                "4.リスク", [],
            )


def _shorten(pool: list[HoldingDecision]) -> None:
    """文章品質の補強: 圧縮・重複除去・100字上限。"""
    for d in pool:
        if d.comment:
            d.comment = compress(d.comment)[:MAX_ITEM_CHARS]
        seen: set[str] = set()
        new: list[str] = []
        for r in d.reasons:
            c = compress(r)[:MAX_ITEM_CHARS]
            if c and c not in seen:
                seen.add(c)
                new.append(c)
        d.reasons = new


def _fix_low(decisions, candidates, pool, low: set[str]) -> None:
    if low & {"分析精度", "整合性", "期待値"}:
        self_improve.improve(decisions, candidates)  # 矛盾/過大の再修正(冪等)
    if low & {"説明性", "ファンダメンタル", "テクニカル", "需給"}:
        _supplement_reasons(pool)
    if "リスク管理" in low:
        _supplement_risk(pool)
    if "文章品質" in low:
        _shorten(pool)


def refine(decisions, candidates, allocation) -> dict[str, int]:
    """全項目90点以上になるまで、90点未満の項目だけを最大5回自動修正する。

    採点結果は返すが表示はしない(呼び出し側でreviewを非表示にする)。decisions等は書換。
    """
    scores: dict[str, int] = {}
    for _ in range(MAX_ITERATIONS):
        pool = _all_decisions(decisions, allocation)
        review = rule_based_review(_ScoringView(decisions, allocation))
        scores = evaluate(decisions, allocation, review)
        low = {dim for dim, s in scores.items() if s < TARGET}
        if not low:
            break
        _fix_low(decisions, candidates, pool, low)
    return scores


class _ScoringView:
    """rule_based_review に渡すための軽量ビュー(decisions/allocation だけ持つ)。"""

    def __init__(self, decisions, allocation):
        self.decisions = decisions
        self.allocation = allocation
