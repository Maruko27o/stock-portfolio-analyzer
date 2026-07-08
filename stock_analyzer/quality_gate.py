"""⑤ 品質ゲートAI: 分析結果の最終品質保証(検査のみ・書き換えは行わない)。

役割は「最終品質保証」だけ。分析はしないし、内容も書き換えない。問題を見つけたら
自己改修AI(③)へ差し戻し、修正後に再度ゲートを通す。最大3回まで。通過した分析のみ
最終出力AI(⑥)へ渡す。責務分離のため、修正は必ず self_improve 側に委ねる。

チェック項目(ユーザー指定):
数値の矛盾/スコアと判断の一致/強い買いなのに極端な割高/売却なのに期待が高すぎ/
保有コメントと判断の一致/根拠不足/説明と結論の一致/説明の繰り返し/重要情報が上から/
RRと期待の矛盾/リスクと買い判断の整合/期待が現実的か/不自然な100点/データ欠損。
"""

from __future__ import annotations

from stock_analyzer import config
from stock_analyzer.conclusion import BUY_ACTIONS
from stock_analyzer.decision import SELL_ACTIONS, HoldingDecision
from stock_analyzer.review import rule_based_review

MAX_GATE_PASSES = 3
# 「極端な割高」「期待が高すぎ」の閾値。
EXTREME_OVERVALUED = 12.0
UNREALISTIC_RETURN = 40.0
# [カテゴリ9] 品質ゲート未通過/整合違反があるとき、分析信頼度をこの上限まで引き下げる。
GATE_FAIL_CONFIDENCE_CAP = 60


def _long_term(d: HoldingDecision):
    return next((h for h in d.expected_returns if h.label == "半年〜1年"), None)


def _pool(data) -> list[HoldingDecision]:
    pool = list(getattr(data, "decisions", []))
    alloc = getattr(data, "allocation", None)
    if alloc is not None:
        seen = {id(d) for d in pool}
        for d in alloc.ranking:
            if id(d) not in seen:
                pool.append(d)
    return pool


def gate_check(data) -> list[str]:
    """品質上の問題を文字列で列挙する(空なら合格)。内容は一切書き換えない。"""
    issues: list[str] = []

    # 論理・整合系はレビューAIの検査を借用(検出のみ)。
    for f in rule_based_review(data):
        issues.append(f"{f.symbol or '全体'}: {f.issue}")

    for d in _pool(data):
        tag = d.symbol
        lt = _long_term(d)
        # データ欠損
        if d.current_price is None:
            issues.append(f"{tag}: 現在値が欠損")
        if not d.expected_returns:
            issues.append(f"{tag}: 期待リターンが欠損")
        # 強い買いなのに極端な割高
        if d.action == "強く買い増し" and d.discount_pct is not None and d.discount_pct >= EXTREME_OVERVALUED:
            issues.append(f"{tag}: 強い買いだが極端に割高({d.discount_pct:+.0f}%)")
        # [カテゴリ2] 割高(割安率>0)のハード制約: スコア上限超 or 強い買い
        if d.discount_pct is not None and d.discount_pct > config.OVERVALUED_DISCOUNT_PCT and (
            d.overall_score > config.OVERVALUED_SCORE_CAP or d.action == "強く買い増し"
        ):
            issues.append(
                f"{tag}: 割高だが{d.overall_score}点/「{d.action}」(上限{config.OVERVALUED_SCORE_CAP}点)"
            )
        # 売却なのに期待リターンが高すぎ
        if d.action in SELL_ACTIONS and lt is not None and lt.pct is not None and lt.pct >= 15:
            issues.append(f"{tag}: 売却判断だが期待リターンが高い({lt.pct:+.0f}%)")
        # 期待が非現実的
        if lt is not None and lt.pct is not None and lt.pct > UNREALISTIC_RETURN:
            issues.append(f"{tag}: 期待リターンが非現実的({lt.pct:+.0f}%)")
        # 保有コメントと最終判断の一致(買い方向コメントで売り判断など)
        if d.comment:
            buy_words = ("買い", "追加", "最優先")
            if d.action in SELL_ACTIONS and any(w in d.comment for w in buy_words):
                issues.append(f"{tag}: 保有コメントと判断が不一致")
        # 根拠不足(買い判断だが理由も数値根拠も無い)
        if d.action in BUY_ACTIONS and not d.reasons and d.discount_pct is None and not d.dividend_yield:
            issues.append(f"{tag}: 買い判断の根拠不足")
        # 説明の繰り返し(同一理由の重複)
        if d.reasons and len(d.reasons) != len(set(d.reasons)):
            issues.append(f"{tag}: 説明の繰り返しあり")

    # 重要情報が上から並んでいるか(スコア降順で並んでいるか)
    decisions = list(getattr(data, "decisions", []))
    scores = [d.overall_score for d in decisions]
    if scores != sorted(scores, reverse=True):
        issues.append("全体: 銘柄がスコア降順に並んでいない(重要情報が上に来ていない)")

    return issues


def run_gate(data, on_fix) -> tuple[bool, int, list[str]]:
    """ゲートを通す。問題があれば on_fix()(=③自己改修へ差し戻し)を呼び、最大3回まで再検査。

    on_fix は「自己改修＋配分/結論の再計算」を行うコールバック(quality_gate は書き換えない)。
    戻り値: (通過したか, 実施した差し戻し回数, 残った問題)。
    """
    issues = gate_check(data)
    passes = 0
    while issues and passes < MAX_GATE_PASSES:
        on_fix()  # 差し戻し(自己改修AIが修正)
        passes += 1
        issues = gate_check(data)
    return (not issues), passes, issues


def confidence(data) -> tuple[int, str, list[str]]:
    """分析信頼度(%)・★・理由を返す。データ充足率＋レビュー通過＋ゲート通過から算出。"""
    pool = _pool(data)
    if not pool:
        return 0, "☆☆☆☆☆", ["分析対象なし"]

    def fill(d: HoldingDecision) -> float:
        fields = [
            d.current_price is not None,
            d.discount_pct is not None or bool(d.dividend_yield),
            _long_term(d) is not None and _long_term(d).pct is not None,
            bool(d.supply_demand_stars),
            d.risk_reward is not None or d.action not in BUY_ACTIONS,
        ]
        return sum(1 for x in fields if x) / len(fields)

    fill_rate = sum(fill(d) for d in pool) / len(pool)
    review_clean = not getattr(data, "review", [])
    gate_passed = getattr(data, "gate_passed", False)
    violations = getattr(data, "violations", []) or []

    pct = round(55 + 35 * fill_rate + (5 if review_clean else 0) + (5 if gate_passed else 0))
    pct = max(0, min(100, pct))
    reasons = [
        f"データ充足率{fill_rate * 100:.0f}%",
        "レビュー通過" if review_clean else "レビュー指摘あり",
        "品質ゲート通過" if gate_passed else "品質ゲート未通過",
    ]
    # [カテゴリ9] 内部チェック(品質ゲート/最終整合)が未通過なら信頼度を自動的に引き下げ、
    # 「参考値」であることを明示する。高信頼度と未通過が併存する矛盾を構造的に防ぐ。
    if not gate_passed or violations:
        pct = min(pct, GATE_FAIL_CONFIDENCE_CAP)
        reasons.append("品質チェック未完了のため参考値(信頼度を引き下げ)")
    filled = min(5, max(1, round(pct / 20)))
    stars = "★" * filled + "☆" * (5 - filled)
    return pct, stars, reasons
